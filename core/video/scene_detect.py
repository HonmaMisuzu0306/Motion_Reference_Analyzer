from pathlib import Path
from typing import Any

import av

from video.orientation import display_bgr
from video.scene_features import SCENE_CUT_THRESHOLD, SceneBoundaryDetector
from video.timing import picture_end, relative_frame_time


def detect_scenes(
    video_path: str | Path,
    threshold: float = SCENE_CUT_THRESHOLD,
    min_shot_duration: float = 0.0,
) -> list[dict[str, Any]]:
    """结合空间变化、连续平移与闪光证据检测硬切，默认保留快速剪辑。"""
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"视频文件不存在: {path}")

    cuts = [0.0]
    detector = SceneBoundaryDetector(threshold)

    def publish(times):
        for timestamp in times:
            if timestamp > cuts[-1] and timestamp - cuts[-1] >= min_shot_duration:
                cuts.append(timestamp)

    with av.open(str(path)) as container:
        video_stream = next(s for s in container.streams if s.type == "video")
        time_base = video_stream.time_base
        duration = float(video_stream.duration * time_base) if video_stream.duration is not None else 0.0

        for frame in container.decode(video_stream):
            current_time = relative_frame_time(video_stream, frame.pts, frame.time_base)
            if video_stream.duration is None:
                duration = max(duration, picture_end(video_stream, frame))
            img = display_bgr(frame, video_stream)
            publish(detector.push(current_time, img))

        publish(detector.finish())

    if cuts[-1] < duration:
        cuts.append(duration)

    shots = []
    for idx in range(len(cuts) - 1):
        start = cuts[idx]
        end = cuts[idx + 1]
        shots.append({
            "shot_id": f"shot_{idx + 1:03d}",
            "start": start,
            "end": end,
            "duration": end - start,
        })

    if not shots:
        shots.append({
            "shot_id": "shot_001",
            "start": 0.0,
            "end": duration,
            "duration": duration,
        })

    return shots
