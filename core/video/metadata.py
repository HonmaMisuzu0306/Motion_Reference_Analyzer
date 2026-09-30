from pathlib import Path
from typing import Any

import av


def read_video_metadata(video_path: str | Path) -> dict[str, Any]:
    """读取视频元数据，返回时长、分辨率、帧率、编码等信息。"""
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"视频文件不存在: {path}")

    with av.open(str(path)) as container:
        video_stream = next(
            (s for s in container.streams if s.type == "video"),
            None,
        )
        if video_stream is None:
            raise ValueError(f"未找到视频流: {path}")

        duration = float(container.duration / av.time_base) if container.duration else 0.0
        fps = float(video_stream.average_rate) if video_stream.average_rate else 0.0
        width = video_stream.codec_context.width
        height = video_stream.codec_context.height
        codec = video_stream.codec_context.codec.name if video_stream.codec_context.codec else "unknown"
        bitrate = container.bit_rate or 0

        return {
            "filename": path.name,
            "duration": round(duration, 3),
            "width": width,
            "height": height,
            "fps": round(fps, 3),
            "codec": codec,
            "bitrate": bitrate,
            "has_audio": any(s.type == "audio" for s in container.streams),
        }
