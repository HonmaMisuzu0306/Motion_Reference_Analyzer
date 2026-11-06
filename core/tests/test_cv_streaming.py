from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from cv import frame_sampler


class FakeContainer:
    def __init__(self, timestamps):
        self.timestamps = timestamps
        self.decoded = 0
        self.closed = False
        self.streams = [SimpleNamespace(type='video', time_base=Fraction(1, 24), start_time=0)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def seek(self, *args, **kwargs):
        pass

    def decode(self, stream):
        for pts in self.timestamps:
            self.decoded += 1
            yield SimpleNamespace(pts=pts, to_ndarray=lambda **kwargs: np.zeros((8, 8, 3), dtype=np.uint8))


def test_sampler_yields_before_decoding_remaining_video_and_closes_early(tmp_path, monkeypatch):
    path = tmp_path / 'video.mp4'
    path.touch()
    container = FakeContainer(range(2400))
    monkeypatch.setattr(frame_sampler.av, 'open', lambda path: container)
    frames = frame_sampler.iter_frames_for_cv(path, 0, 100)
    assert container.decoded == 0
    first = next(frames)
    assert first['timestamp'] == 0 and container.decoded == 1
    assert not container.closed
    frames.close()
    assert container.closed


def test_streamed_sampling_retains_last_frame_without_duplicate(tmp_path, monkeypatch):
    path = tmp_path / 'video.mp4'
    path.touch()
    container = FakeContainer(range(24))
    monkeypatch.setattr(frame_sampler.av, 'open', lambda path: container)
    times = [f['timestamp'] for f in frame_sampler.iter_frames_for_cv(path, 0, 1)]
    assert times == pytest.approx([0, .125, .25, .375, .5, .625, .75, .875, 23 / 24])
    assert container.closed


def test_stream_error_closes_container(tmp_path, monkeypatch):
    path = tmp_path / 'video.mp4'
    path.touch()
    container = FakeContainer([0, 0])
    monkeypatch.setattr(frame_sampler.av, 'open', lambda path: container)
    frames = frame_sampler.iter_frames_for_cv(path, 0, 1)
    next(frames)
    with pytest.raises(ValueError, match='严格递增'):
        next(frames)
    assert container.closed
