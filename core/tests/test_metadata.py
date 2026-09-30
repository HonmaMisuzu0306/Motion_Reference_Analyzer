from pathlib import Path

import numpy as np

from video.metadata import read_video_metadata


def _create_test_video(path: Path, duration: float = 1.0, fps: int = 24) -> Path:
    """创建测试用 MP4 视频。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 320, 240
    total_frames = int(duration * fps)

    import av
    with av.open(str(path), "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"

        for i in range(total_frames):
            frame = av.VideoFrame.from_ndarray(
                np.full((height, width, 3), i % 256, dtype=np.uint8),
                format="bgr24",
            )
            for packet in stream.encode(frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

    return path


def test_read_video_metadata(tmp_path: Path):
    video = _create_test_video(tmp_path / "test.mp4", duration=2.0, fps=24)
    meta = read_video_metadata(video)

    assert meta["filename"] == "test.mp4"
    assert meta["width"] == 320
    assert meta["height"] == 240
    assert meta["fps"] == 24.0
    assert meta["duration"] >= 1.9
