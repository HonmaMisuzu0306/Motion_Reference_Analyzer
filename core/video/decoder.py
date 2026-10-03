from pathlib import Path

import av
import numpy as np

from video.frame_sampler import _decode_nearest_frame


def extract_frame(video_path: str | Path, timestamp: float) -> np.ndarray:
    """从视频中提取指定时间戳的帧（BGR 格式，OpenCV 兼容）。"""
    path = Path(video_path)
    with av.open(str(path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        return _decode_nearest_frame(container, video_stream, timestamp)
