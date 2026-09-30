from pathlib import Path

import av
import numpy as np


def extract_frame(video_path: str | Path, timestamp: float) -> np.ndarray:
    """从视频中提取指定时间戳的帧（BGR 格式，OpenCV 兼容）。"""
    path = Path(video_path)
    with av.open(str(path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        video_stream.codec_context.skip_frame = "NONKEY"

        # seek 到目标时间戳附近的关键帧
        target_pts = int(timestamp * video_stream.time_base.denominator / video_stream.time_base.numerator)
        container.seek(target_pts, stream=video_stream)

        for frame in container.decode(video_stream):
            frame_pts = float(frame.pts * video_stream.time_base)
            if frame_pts >= timestamp:
                return frame.to_ndarray(format="bgr24")

    raise RuntimeError(f"无法在 {video_path} 中提取 {timestamp}s 处的帧")
