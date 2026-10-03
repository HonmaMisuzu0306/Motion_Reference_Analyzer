from pathlib import Path
from typing import Any

import av
import numpy as np
from PIL import Image

from video.timing import video_origin


def sample_frames(
    video_path: str | Path,
    start: float,
    end: float,
    count: int = 3,
) -> list[dict[str, Any]]:
    """按百分比策略从指定时间区间内采样代表帧。"""
    if count <= 0:
        raise ValueError("count 必须大于 0")

    duration = end - start
    frames = []
    with av.open(str(video_path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")

        for i in range(1, count + 1):
            ratio = i / (count + 1)
            timestamp = start + duration * ratio
            frame = _decode_nearest_frame(container, video_stream, timestamp)
            frames.append({
                "timestamp": round(timestamp, 3),
                "image": frame,
            })

    return frames


def _decode_nearest_frame(
    container: av.container.InputContainer,
    video_stream: av.VideoStream,
    target_timestamp: float,
) -> np.ndarray:
    """解码最接近目标时间戳的帧。"""
    video_stream.codec_context.skip_frame = "NONE"
    origin = video_origin(video_stream)
    target_pts = int((target_timestamp + origin) / video_stream.time_base)
    container.seek(target_pts, stream=video_stream)

    best_frame = None
    best_diff = float("inf")
    for frame in container.decode(video_stream):
        frame_pts = float(frame.pts * video_stream.time_base) - origin
        diff = abs(frame_pts - target_timestamp)
        if diff < best_diff:
            best_diff = diff
            best_frame = frame.to_ndarray(format="bgr24")
        if frame_pts >= target_timestamp:
            break

    if best_frame is None:
        raise RuntimeError(f"无法在目标时间 {target_timestamp}s 附近解码帧")

    return best_frame


def create_contact_sheet(
    frames: list[np.ndarray],
    output_path: str | Path,
    max_width: int = 1920,
) -> Path:
    """将多张帧横向拼接成 Contact Sheet。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    images = [Image.fromarray(frame) for frame in frames]
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
