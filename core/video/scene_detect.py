from pathlib import Path
from typing import Any

import av
import numpy as np


def _frame_hash(frame: np.ndarray, bins: int = 16) -> np.ndarray:
    """生成降采样后的帧特征向量，用于快速比较。"""
    h, w = frame.shape[:2]
    small = frame[::h // bins, ::w // bins]
    return np.mean(small.reshape(-1, 3), axis=0)


def detect_scenes(
    video_path: str | Path,
    threshold: float = 25.0,
    min_shot_duration: float = 0.5,
) -> list[dict[str, Any]]:
    """基于帧间差异的简单分镜检测。

    在无法使用 PySceneDetect 的环境中作为降级方案。
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"视频文件不存在: {path}")

    cuts = [0.0]
    prev_hash = None
    prev_time = 0.0

    with av.open(str(path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        time_base = float(video_stream.time_base)

        for frame in container.decode(video_stream):
            current_time = float(frame.pts * time_base)
            img = frame.to_ndarray(format="bgr24")
            current_hash = _frame_hash(img)

            if prev_hash is not None:
                diff = float(np.linalg.norm(current_hash - prev_hash))
                if diff > threshold and (current_time - prev_time) >= min_shot_duration:
                    cuts.append(current_time)
                    prev_time = current_time

            prev_hash = current_hash

        duration = (
            float(container.duration / av.time_base)
            if container.duration
            else current_time
        )

    if cuts[-1] < duration:
        cuts.append(duration)

    shots = []
    for idx in range(len(cuts) - 1):
        start = cuts[idx]
        end = cuts[idx + 1]
        shots.append({
            "shot_id": f"shot_{idx + 1:03d}",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
        })

    if not shots:
        shots.append({
            "shot_id": "shot_001",
            "start": 0.0,
            "end": round(duration, 3),
            "duration": round(duration, 3),
        })

    return shots
