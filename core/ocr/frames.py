"""OCR 专用帧采样。

与代表帧提取不同，OCR 需要时间密度更高（4–8 fps），
但同时限制最大帧数以控制成本。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import av
import numpy as np
from PIL import Image

from video.timing import video_origin


def sample_ocr_frames(
    video_path: str | Path,
    start: float,
    end: float,
    target_fps: float = 6.0,
    min_frames: int = 3,
    max_frames: int = 12,
    max_long_edge: int = 960,
    strict_range: bool = False,
) -> list[dict[str, Any]]:
    """从 Shot 时间区间内采样用于 OCR 的帧。

    策略：
    - 按 target_fps 均匀采样；
    - 短镜保证 min_frames；
    - 长镜限制 max_frames；
    - 返回帧最长边不超过 max_long_edge（等比缩放）。
    """
    duration = max(0.0, end - start)
    if duration <= 0:
        return []

    frame_count = max(min_frames, min(max_frames, int(duration * target_fps)))
    if frame_count <= 0:
        return []

    if strict_range:
        from selection.media import sample_range_frames

        result = []
        for frame in sample_range_frames(Path(video_path), start, end, frame_count):
            resized = _resize_long_edge(frame.image, max_long_edge)
            result.append({'timestamp': frame.identity.actual_time, 'image': resized,
                           'width': resized.shape[1], 'height': resized.shape[0]})
        return result

    frames: list[dict[str, Any]] = []
    with av.open(str(video_path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        time_base = float(video_stream.time_base)
        origin = video_origin(video_stream)

        for i in range(1, frame_count + 1):
            ratio = i / (frame_count + 1)
            timestamp = start + duration * ratio

            target_pts = int((timestamp + origin) / time_base)
            try:
                container.seek(target_pts, stream=video_stream)
            except av.AVError:
                continue

            best_frame = None
            best_diff = float("inf")
            for frame in container.decode(video_stream):
                frame_pts = float(frame.pts * time_base) - origin
                diff = abs(frame_pts - timestamp)
                if diff < best_diff:
                    best_diff = diff
                    best_frame = frame.to_ndarray(format="bgr24")
                if frame_pts >= timestamp:
                    break

            if best_frame is None:
                continue

            resized = _resize_long_edge(best_frame, max_long_edge)
            frames.append({
                "timestamp": round(timestamp, 3),
                "image": resized,
                "width": resized.shape[1],
                "height": resized.shape[0],
            })

    return frames


def _resize_long_edge(image: np.ndarray, max_long_edge: int) -> np.ndarray:
    """等比缩放图像，使最长边不超过 max_long_edge。"""
    h, w = image.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_long_edge:
        return image
    scale = max_long_edge / long_edge
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = Image.fromarray(image).resize((new_w, new_h), Image.Resampling.LANCZOS)
    return np.array(resized)
