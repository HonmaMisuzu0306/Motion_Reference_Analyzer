from math import isfinite
from pathlib import Path
from typing import Any

import av
import numpy as np
from PIL import Image

from video.orientation import display_bgr
from video.timing import relative_frame_time, video_origin


def sample_frames(
    video_path: str | Path,
    start: float,
    end: float,
    count: int = 3,
) -> list[dict[str, Any]]:
    """Return unique representative frames with actual PTS in [start, end)."""
    if count <= 0:
        raise ValueError("count 必须大于 0")
    if not all(isfinite(value) for value in (start, end)) or not 0 <= start < end:
        raise ValueError('代表帧时间范围必须满足 0 <= start < end，且为有限数值')

    duration = end - start
    frames = {}
    with av.open(str(video_path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        targets = [start + duration * i / (count + 1) for i in range(1, count + 1)]
        for frame in _decode_nearest_records(container, video_stream, targets, start=start, end=end):
            frames.setdefault(frame['pts'], {'timestamp': frame['timestamp'], 'image': frame['image']})

    return sorted(frames.values(), key=lambda frame: frame['timestamp'])


def _decode_nearest_frame(
    container: av.container.InputContainer,
    video_stream: av.VideoStream,
    target_timestamp: float,
) -> np.ndarray:
    """Compatibility helper for single-time extraction, returning BGR pixels."""
    return _decode_nearest_records(container, video_stream, [target_timestamp])[0]['image']


def _decode_nearest_records(
    container: av.container.InputContainer,
    video_stream: av.VideoStream,
    targets: list[float],
    *,
    start: float | None = None,
    end: float | None = None,
) -> list[dict[str, Any]]:
    """Decode nearest actual frame, with optional strict half-open evidence bounds."""
    if not targets or any(not isfinite(target) or target < 0 for target in targets):
        raise ValueError('目标帧时间必须为非负有限数值')
    video_stream.codec_context.skip_frame = "NONE"
    origin = video_origin(video_stream)
    # One bounded decoding pass keeps the first eligible frame available even
    # when a tiny interval's nominal target rounds up to its excluded end.
    seek_time = start if start is not None else targets[0]
    target_pts = int((seek_time + origin) / video_stream.time_base)
    container.seek(target_pts, stream=video_stream, backward=True)

    best_frames = [None] * len(targets)
    best_diffs = [float('inf')] * len(targets)
    for frame in container.decode(video_stream):
        if frame.pts is None:
            raise ValueError('视频帧缺少实际时间戳')
        actual_time = relative_frame_time(video_stream, frame.pts, frame.time_base)
        if start is not None and actual_time < start:
            continue
        if end is not None and actual_time >= end:
            break
        distances = [abs(actual_time - target) for target in targets]
        improved = [index for index, distance in enumerate(distances) if distance < best_diffs[index]]
        if improved:
            chosen = {'pts': frame.pts, 'timestamp': actual_time,
                      'image': display_bgr(frame, video_stream)}
            for index in improved:
                best_frames[index], best_diffs[index] = chosen, distances[index]
        if actual_time >= targets[-1]:
            break

    if any(frame is None for frame in best_frames):
        if start is not None and end is not None:
            raise RuntimeError(f'指定范围 [{start}, {end}) 内没有可解码帧')
        raise RuntimeError(f'无法在目标时间 {targets}s 附近解码帧')

    return best_frames


def create_contact_sheet(
    frames: list[np.ndarray],
    output_path: str | Path,
    max_width: int = 1920,
) -> Path:
    """将 BGR 帧转换为 RGB 后横向拼接成 Contact Sheet。"""
    if not frames:
        raise ValueError('联系表至少需要一帧画面')
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    images = [Image.fromarray(frame[:, :, ::-1]) for frame in frames]
    if max_width:
        total_width = sum(img.width for img in images)
        if total_width > max_width:
            scale = max_width / total_width
            images = [img.resize((int(img.width * scale), int(img.height * scale))) for img in images]

    widths, heights = zip(*(img.size for img in images))
    total_width = sum(widths)
    max_height = max(heights)

    contact = Image.new("RGB", (total_width, max_height))
    x_offset = 0
    for img in images:
        contact.paste(img, (x_offset, 0))
        x_offset += img.width

    contact.save(output_path, quality=90)
    return output_path
