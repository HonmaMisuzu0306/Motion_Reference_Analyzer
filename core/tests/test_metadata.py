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

def test_fractional_fps_last_shot_can_be_selected(tmp_path):
    from fractions import Fraction

    from selection.models import validate_range
    from video.scene_detect import detect_scenes

    rate = Fraction(24000, 1001)
    video = _create_test_video(tmp_path / 'fractional.mp4', duration=0.13, fps=rate)
    meta = read_video_metadata(video)
    last = detect_scenes(video)[-1]
    validate_range(last['start'], last['end'], meta['duration'])
    assert meta['duration'] == last['end'] == float(3 / rate)
    assert meta['fps'] == float(rate)


def test_audio_lead_in_does_not_extend_picture_selection(tmp_path):
    from tests.test_audio import write_av_video

    # Sound starts one second before picture. Selection times start at the first picture.
    video = write_av_video(tmp_path / 'lead-in.mp4', duration=1, origin=2, offset=-1)
    assert read_video_metadata(video)['duration'] == 1


def test_video_without_stream_duration_uses_last_picture_end(tmp_path):
    import pytest

    from tests.test_audio import write_av_video
    from video.scene_detect import detect_scenes

    video = write_av_video(tmp_path / 'lead-in.mkv', duration=1, origin=2, offset=-1)
    duration = read_video_metadata(video)['duration']
    assert duration == pytest.approx(1, abs=.002)
    assert detect_scenes(video)[-1]['end'] == duration
