from collections.abc import Iterator
from math import floor, isfinite
from pathlib import Path
from typing import Any, BinaryIO

import av
import cv2
import numpy as np

from video.orientation import display_bgr, display_dimensions
from video.timing import relative_frame_time, video_origin

CV_ANALYSIS_MAX_LONG_EDGE = 720
CV_ANALYSIS_TARGET_FPS = 8
# Comparing a decoded PTS with a floating sampling grid needs a tiny tolerance:
# e.g. (10 + 1/24) - 10 can fall just below 1/24. This tolerance never widens
# the half-open shot interval and does not change emitted source timestamps.
SAMPLING_TIME_EPSILON = 1e-9


def _resize_for_analysis(frame: np.ndarray, max_long_edge: int) -> np.ndarray:
    """将帧等比缩放，使最长边不超过 max_long_edge。"""
    h, w = frame.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_long_edge:
        return frame

    scale = max_long_edge / long_edge
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _check_stream_pixels(stream, limit):
    width, height = display_dimensions(stream)
    context = stream.codec_context
    if max(context.width * context.height, width * height) > limit:
        raise ValueError('源视频编码或显示画幅超出像素预算')


def iter_frames_for_cv(
    video_path: str | Path | BinaryIO,
    start_time: float,
    end_time: float,
    target_fps: float = CV_ANALYSIS_TARGET_FPS,
    max_long_edge: int = CV_ANALYSIS_MAX_LONG_EDGE,
    *,
    max_decoded_frames: int | None = None,
    max_source_pixels: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield sampled frames without retaining all decoded images in memory.

    Times are actual PTS in the half-open shot range, including its last frame.
    Closing the generator releases its container even if the caller stops early.
    """
    if isinstance(video_path, (str, Path)):
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"视频文件不存在: {path}")
        source = str(path)
    else:
        source = video_path
        source.seek(0)

    if not all(isfinite(value) for value in (start_time, end_time, target_fps)):
        raise ValueError('采样时间和帧率必须为有限数值')
    if not 0 <= start_time < end_time or target_fps <= 0 or max_long_edge < 1:
        raise ValueError(f"Shot 时间范围无效: {start_time} - {end_time}")

    with av.open(source) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        if max_source_pixels is not None:
            _check_stream_pixels(video_stream, max_source_pixels)
        time_base = video_stream.time_base
        origin = video_origin(video_stream)

        start_pts = int((start_time + origin) / time_base)
        container.seek(start_pts, stream=video_stream, backward=True)

        next_pts_threshold = start_time
        last_frame = None
        last_time = None
        last_emitted_time = None

        def sample(frame, timestamp):
            bgr = display_bgr(frame, video_stream)
            return {
                "timestamp": timestamp,
                "image": _resize_for_analysis(bgr, max_long_edge),
                "original_height": bgr.shape[0], "original_width": bgr.shape[1],
            }

        for index, frame in enumerate(container.decode(video_stream)):
            if max_decoded_frames is not None and index >= max_decoded_frames:
                raise ValueError('解码帧数超出预算，请缩短时间范围')
            if max_source_pixels is not None and frame.width * frame.height > max_source_pixels:
                raise ValueError('源视频编码画幅超出像素预算')
            if frame.pts is None:
                raise ValueError('视频帧缺少实际时间戳')
            current_time = relative_frame_time(video_stream, frame.pts, getattr(frame, 'time_base', None))
            if current_time < start_time:
                continue
            if current_time >= end_time:
                break

            if last_time is not None and current_time <= last_time:
                raise ValueError('视频帧时间戳没有严格递增')
            last_frame, last_time = frame, current_time
            if current_time + SAMPLING_TIME_EPSILON >= next_pts_threshold:
                yield sample(frame, current_time)
                last_emitted_time = current_time
                next_pts_threshold = start_time + (floor((current_time - start_time + SAMPLING_TIME_EPSILON) * target_fps) + 1) / target_fps

        if last_frame is not None and (last_emitted_time is None or last_emitted_time < last_time):
            yield sample(last_frame, last_time)


def sample_frames_for_cv(
    video_path: str | Path,
    start_time: float,
    end_time: float,
    target_fps: float = CV_ANALYSIS_TARGET_FPS,
    max_long_edge: int = CV_ANALYSIS_MAX_LONG_EDGE,
) -> list[dict[str, Any]]:
    """Compatibility helper for consumers that explicitly need all sample images."""
    return list(iter_frames_for_cv(video_path, start_time, end_time, target_fps, max_long_edge))
