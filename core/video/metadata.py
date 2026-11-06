from pathlib import Path
from typing import Any

import av

from video.orientation import display_dimensions
from video.timing import picture_end


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

        # Selection and scene boundaries use the video clock. Audio can start
        # earlier or end later, so the container length may include no picture.
        if video_stream.duration is not None:
            duration = float(video_stream.duration * video_stream.time_base)
        else:
            # Matroska often omits the stream duration. Read compressed packet
            # timestamps in presentation order by taking the maximum (B-frames).
            duration = max((picture_end(video_stream, packet) for packet in container.demux(video_stream)
                            if packet.pts is not None), default=0.0)
        fps = float(video_stream.average_rate) if video_stream.average_rate else 0.0
        width, height = display_dimensions(video_stream)
        codec = video_stream.codec_context.codec.name if video_stream.codec_context.codec else "unknown"
        bitrate = container.bit_rate or 0

        return {
            "filename": path.name,
            "duration": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "codec": codec,
            "bitrate": bitrate,
            "has_audio": any(s.type == "audio" for s in container.streams),
        }
