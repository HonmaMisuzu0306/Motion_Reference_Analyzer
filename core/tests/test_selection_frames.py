"""Real VFR/B-frame presentation identities, never an invented frame number."""
from fractions import Fraction

import av
import numpy as np
import pytest

from selection.frames import iter_range_frames, locate_frame
from selection.models import validate_range
from tests.test_audio import write_av_video


def write_vfr(path):
    with av.open(str(path), 'w') as out:
        stream = out.add_stream('libx264', rate=25)
        stream.width, stream.height, stream.pix_fmt = 160, 120, 'yuv420p'
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for pts, value in [(0, 20), (40, 100), (110, 220)]:
            frame = av.VideoFrame.from_ndarray(np.full((120, 160, 3), value, np.uint8), format='bgr24')
            frame.pts, frame.time_base = pts, Fraction(1, 1000)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    return path


def test_presentation_time_chooses_previous_not_nearest_future(tmp_path):
    source = write_vfr(tmp_path / 'vfr.mp4')
    frame = locate_frame(source, .10)
    assert frame.identity.actual_time == pytest.approx(.04)
    assert frame.image.mean() == pytest.approx(100, abs=4)
    assert [f.identity.actual_time for f in iter_range_frames(source, .04, .11)] == [.04]


def test_adjacent_frames_and_edges(tmp_path):
    source = write_vfr(tmp_path / 'vfr.mp4')
    middle = locate_frame(source, .1)
    last = locate_frame(source, .1, pts=middle.identity.pts, direction='next')
    assert last.identity.actual_time == pytest.approx(.11)
    assert locate_frame(source, .11, pts=last.identity.pts, direction='previous').identity.pts == middle.identity.pts
    assert locate_frame(source, 0, direction='previous').identity.actual_time == 0
    assert locate_frame(source, .15, direction='next').identity.actual_time == pytest.approx(.11)
    with pytest.raises(ValueError, match='PTS'):
        locate_frame(source, .04, pts=1234567)


def test_b_frames_nonzero_origin_and_duration_return_real_last_frame(tmp_path):
    source = write_av_video(tmp_path / 'shifted.mp4', origin=10, duration=1, audio=False)
    frame = locate_frame(source, .10)
    assert frame.identity.actual_time == pytest.approx(2 / 24)
    assert frame.identity.video_origin == 10
    assert locate_frame(source, 1).identity.actual_time == pytest.approx(23 / 24)
    assert frame.identity.source_hash and frame.identity.time_base_den > 0


def test_fractional_23976_frame_rate_keeps_presentation_pts(tmp_path):
    path = tmp_path / 'fractional.mp4'
    with av.open(str(path), 'w') as out:
        stream = out.add_stream('libx264', rate=Fraction(24000, 1001))
        stream.width, stream.height, stream.pix_fmt = 160, 120, 'yuv420p'
        for i in range(24):
            frame = av.VideoFrame.from_ndarray(np.full((120, 160, 3), i * 8, np.uint8), format='bgr24')
            frame.pts, frame.time_base = i, Fraction(1001, 24000)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    current = locate_frame(path, .1)
    assert current.identity.actual_time == pytest.approx(2 * 1001 / 24000)
    assert locate_frame(path, 1).identity.actual_time == pytest.approx(23 * 1001 / 24000)


def test_compositor_microsecond_clock_and_manual_instant_choose_different_frames(tmp_path):
    path = write_av_video(tmp_path / 'clock.mp4', origin=10, duration=2, audio=False)
    # 17/24 is displayed as 0.708333 seconds, slightly before its rational PTS.
    timestamp = .708333
    assert locate_frame(path, timestamp, direction='presented').identity.actual_time == 17 / 24
    assert locate_frame(path, timestamp).identity.actual_time == 16 / 24
    assert locate_frame(path, 1.416667, direction='presented').identity.actual_time == 34 / 24


@pytest.mark.parametrize('start,end,duration', [(float('nan'), 1, 2), (0, float('inf'), 2),
                                             (-1, 1, 2), (1, 1, 2), (2, 1, 3), (0, 61, 70), (0, 3, 2)])
def test_invalid_range_rejected(start, end, duration):
    with pytest.raises(ValueError):
        validate_range(start, end, duration)
