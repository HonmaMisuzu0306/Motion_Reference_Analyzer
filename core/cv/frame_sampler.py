from pathlib import Path
from typing import Any

import av
import cv2
import numpy as np

from video.timing import video_origin

CV_ANALYSIS_MAX_LONG_EDGE = 720
CV_ANALYSIS_TARGET_FPS = 8


def _resize_for_analysis(frame: np.ndarray, max_long_edge: int) -> np.ndarray:
    """将帧等比缩放，使最长边不超过 max_long_edge。"""
    h, w = frame.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_long_edge:
        return frame

    scale = max_long_edge / long_edge
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)


def sample_frames_for_cv(
    video_path: str | Path,
    start_time: float,
    end_time: float,
    target_fps: float = CV_ANALYSIS_TARGET_FPS,
    max_long_edge: int = CV_ANALYSIS_MAX_LONG_EDGE,
) -> list[dict[str, Any]]:
    """从 Shot 时间范围内按目标帧率采样连续帧，用于 CV 运动分析。

    返回每个帧的时间戳和缩放后的 BGR 图像。
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"视频文件不存在: {path}")

    duration = end_time - start_time
    if duration <= 0:
        raise ValueError(f"Shot 时间范围无效: {start_time} - {end_time}")

    frames: list[dict[str, Any]] = []

    with av.open(str(path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        time_base = video_stream.time_base
        origin = video_origin(video_stream)
        fps = float(video_stream.average_rate) if video_stream.average_rate else target_fps
        step = max(1.0, round(fps / target_fps))

        start_pts = int((start_time + origin) / time_base)
        container.seek(start_pts, stream=video_stream, backward=True)

        target_frame_index = 0
        next_pts_threshold: float | None = None

        for frame in container.decode(video_stream):
            current_time = float(frame.pts * float(time_base)) - origin
            if current_time < start_time:
                continue
            if current_time >= end_time:
                break

            if next_pts_threshold is None or current_time >= next_pts_threshold:
                bgr = frame.to_ndarray(format="bgr24")
                resized = _resize_for_analysis(bgr, max_long_edge)
                frames.append({
                    "timestamp": round(current_time, 3),
                    "image": resized,
                    "original_height": bgr.shape[0],
                    "original_width": bgr.shape[1],
                })
                target_frame_index += 1
                next_pts_threshold = start_time + (target_frame_index * step / fps)

    return frames
