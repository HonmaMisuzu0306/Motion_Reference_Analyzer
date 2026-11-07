from fractions import Fraction

import av
import numpy as np
import pytest

from cv import region_track
from cv.region_track import NormalizedBox, track_region

W, H = 44, 32
X, Y = 90, 70
FPS = 24


def movie(path, mode='normal', *, oriented=False):
    width, height = (640, 360) if oriented else (384, 216)
    rng = np.random.default_rng(455)
    bg = rng.integers(0, 240, (height, width), dtype=np.uint8)
    texture = rng.integers(0, 255, (H, W), dtype=np.uint8)
    # A uniform grey region well away from its edges tests no-feature handling.
    if mode == 'flat':
        texture.fill(128)
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=FPS)
        stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
        if oriented:
            stream.codec_context.sample_aspect_ratio = Fraction(2, 1)
            stream.set_display_rotation(90)
        for i in range(30):
            frame = np.roll(bg, -2 * i, axis=1)
            x = X + 2 * i
            if i < 18 or mode not in {'cover', 'substitute'}:
                frame[Y:Y+H, x:x+W] = texture
            if i >= 18 and mode in {'copy', 'substitute'}:
                frame[Y:Y+H, x-W-3:x-3] = texture
            image = av.VideoFrame.from_ndarray(frame, format='gray')
            gap = 24 if mode == 'gap' and i >= 12 else 0
            image.pts, image.time_base = 240 + i + gap, Fraction(1, FPS)
            for packet in stream.encode(image):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


def normal_box(anchor_frame=0):
    return NormalizedBox(x=(X+2*anchor_frame)/384, y=Y/216, width=W/384, height=H/216)


def test_tracks_selected_texture_in_opposing_motion_at_real_pts(tmp_path):
    path = tmp_path / 'two-planes.mp4'
    movie(path)
    track = track_region(path, 0.15, 1.0, 0.25, normal_box(6))
    assert track.status == 'complete' and track.stop_time is None
    assert (track.frame_width, track.frame_height) == (384, 216)
    assert [s.source_time for s in track.samples] == [i/FPS for i in (6, 9, 12, 15, 18, 21, 23)]
    for sample in track.samples:
        assert sample.center_x_px == pytest.approx(X+W/2+2*sample.source_time*FPS, abs=.3)
        assert sample.center_y_px == pytest.approx(Y+H/2, abs=.3)


def test_tracks_display_axes_after_sar_rotation_and_downsample(tmp_path):
    path = tmp_path / 'portrait.mp4'
    movie(path, oriented=True)
    # Square pixels double the coded X displacement before rotation by 90° CCW.
    anchor_frame = 6
    start_x = X + 2 * anchor_frame
    box = NormalizedBox(x=Y/360, y=(640-start_x-W)/640, width=H/360, height=W/640)
    track = track_region(path, 0, 1, anchor_frame/FPS, box)
    assert track.status == 'complete'
    assert (track.frame_width, track.frame_height) == (360, 1280)
    assert track.samples[-1].source_time == 23/FPS
    for sample in track.samples:
        assert sample.center_x_px == pytest.approx(Y + H/2, abs=.8)
        assert sample.center_y_px == pytest.approx(2*(640-X-W/2-2*sample.source_time*FPS), abs=.8)


@pytest.mark.parametrize(('mode', 'status'), [
    ('cover', 'no_match'), ('copy', 'ambiguous'), ('substitute', 'abrupt_change'),
])
def test_stops_at_first_unconfirmed_sample(tmp_path, mode, status):
    path = tmp_path / f'{mode}.mp4'
    movie(path, mode)
    track = track_region(path, 0, 1.25, 0, normal_box())
    assert (track.status, track.stop_time) == (status, .75)
    assert track.samples[-1].source_time == .625
    assert all(s.center_x_px == pytest.approx(X + W/2 + 2*s.source_time*FPS, abs=.3)
               for s in track.samples)


def test_anchor_must_match_source_picture_and_cannot_round_to_a_neighbour(tmp_path):
    path = tmp_path / 'anchor.mp4'
    movie(path)
    track = track_region(path, 0, 1, 0.27, normal_box(6))
    assert track.status == 'anchor_mismatch' and track.samples == []
    assert track.stop_time == 7/FPS


def test_vfr_gap_ends_confirmed_prefix_on_actual_next_source_pts(tmp_path):
    path = tmp_path / 'gap.mp4'
    movie(path, 'gap')
    track = track_region(path, 0, 2.25, 0, normal_box())
    assert (track.status, track.stop_time) == ('time_gap', 1.5)
    assert [p.source_time for p in track.samples] == [0, .125, .25, .375]


def test_no_decoded_frame_in_half_open_range(tmp_path):
    path = tmp_path / 'empty-range.mp4'
    movie(path)
    track = track_region(path, 0.001, 0.03, 0.001, normal_box())
    assert (track.status, track.stop_time, track.samples) == ('no_frames', None, [])


def test_full_width_patch_does_not_report_stationary_from_a_single_x_candidate(tmp_path):
    path = tmp_path / 'wide-strip.mp4'
    movie(path)
    box = NormalizedBox(x=0, y=.2, width=1, height=.4)
    track = track_region(path, 0, 1, 0, box)
    assert (track.status, track.stop_time) == ('ambiguous', .125)
    assert [p.source_time for p in track.samples] == [0]


def test_weak_or_too_small_initial_patch_produces_no_track(tmp_path):
    path = tmp_path / 'blank.mp4'
    movie(path, 'flat')
    for box, expected in [(normal_box(), 'insufficient_texture'),
                          (NormalizedBox(x=.1, y=.1, width=.01, height=.1), 'box_too_small')]:
        track = track_region(path, 0, 1, 0, box)
        assert (track.status, track.stop_time, track.samples) == (expected, 0, [])


def test_rejects_invalid_time_or_box_before_opening_video():
    for start, end, anchor in [(0, 31, 0), (1, 2, 0.9), (0, 1, 1), (0, 1, float('nan'))]:
        with pytest.raises(ValueError):
            track_region('missing.mp4', start, end, anchor, normal_box())
    with pytest.raises(ValueError):
        NormalizedBox(x=.9, y=0, width=.2, height=.1)


def test_bounds_decoded_frames_and_pre_resize_pixel_count(tmp_path, monkeypatch):
    path = tmp_path / 'budget.mp4'
    movie(path, oriented=True)
    monkeypatch.setattr(region_track, 'MAX_DECODED_FRAMES', 1)
    with pytest.raises(ValueError, match='解码帧数'):
        track_region(path, 0, 1, 0, normal_box())
    monkeypatch.setattr(region_track, 'MAX_SOURCE_PIXELS', 640*360)
    with pytest.raises(ValueError, match='像素预算'):
        track_region(path, 0, 1, 0, normal_box())
