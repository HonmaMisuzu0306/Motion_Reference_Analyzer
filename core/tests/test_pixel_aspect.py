"""Non-square samples must become square before applying the track's display matrix."""
import hashlib
import struct
from fractions import Fraction
from types import SimpleNamespace

import av
import cv2
import numpy as np
import pytest

from tests.test_video_orientation import oriented_movie
from video.frame_sampler import sample_frames
from video.metadata import read_video_metadata
from video.orientation import display_bgr, display_dimensions
from video.playback import playback_source


@pytest.mark.parametrize(('ratio', 'normalized', 'angle', 'flip'), [
    (Fraction(4, 3), 64, 0, False),
    (Fraction(2, 3), 32, 90, False),
    (Fraction(17, 32), 26, 270, True),  # 48 * 17/32 = 25.5 -> 26.
])
def test_non_square_track_normalizes_horizontal_axis_first(tmp_path, ratio, normalized, angle, flip):
    source = oriented_movie(tmp_path/'pasp.mp4', angle, flip, sar=ratio)
    with av.open(str(source)) as media:
        stream = media.streams.video[0]
        assert stream.sample_aspect_ratio == ratio
        first = next(media.decode(stream))
        raw = first.to_ndarray(format='bgr24')
        resized = cv2.resize(raw, (normalized, 32),
                             interpolation=cv2.INTER_LINEAR if ratio > 1 else cv2.INTER_AREA)
        expected = np.rot90(resized, angle // 90)
        if flip:
            expected = expected[:, ::-1]
        np.testing.assert_array_equal(display_bgr(first, stream), expected)
    meta = read_video_metadata(source)
    assert (meta['height'], meta['width']) == expected.shape[:2]
    np.testing.assert_array_equal(sample_frames(source, 0, .1, 1)[0]['image'], expected)


def test_remux_preserves_container_override_over_codec_sar(tmp_path):
    source = oriented_movie(tmp_path/'track.mp4', 90, True, shifted=True, sar=Fraction(4, 3))
    # MP4 pasp overrides the VUI ratio in the compressed stream; add_stream_from_template
    # alone silently chooses the VUI on remux. Change only the two fixed-size fields.
    sig = b'pasp' + struct.pack('>II', 4, 3)
    raw = source.read_bytes()
    assert raw.count(sig) == 1
    source.write_bytes(raw.replace(sig, b'pasp' + struct.pack('>II', 2, 1)))
    cache = tmp_path/'preview'
    cache.mkdir()
    stale = cache/(hashlib.sha256(source.read_bytes()).hexdigest() + '-video-clock-v2.mp4')
    stale.write_bytes(b'old incorrect aspect')
    preview = playback_source(source, cache)
    assert preview != stale
    with av.open(str(source)) as a, av.open(str(preview)) as b:
        src, dst = a.streams.video[0], b.streams.video[0]
        assert src.codec_context.sample_aspect_ratio == Fraction(4, 3)
        assert src.sample_aspect_ratio == dst.sample_aspect_ratio == 2
        assert display_dimensions(src) == display_dimensions(dst) == (32, 96)
        np.testing.assert_array_equal(display_bgr(next(a.decode(src)), src), display_bgr(next(b.decode(dst)), dst))


@pytest.mark.parametrize('sar', [None, Fraction(0), Fraction(1)])
def test_square_or_unspecified_does_not_allocate_another_raster(sar):
    pixels = np.empty((5, 7, 3), np.uint8)
    stream = SimpleNamespace(sample_aspect_ratio=sar, codec_context=SimpleNamespace(width=7, height=5))
    frame = SimpleNamespace(to_ndarray=lambda format: pixels)
    assert display_dimensions(stream) == (7, 5)
    assert display_bgr(frame, stream) is pixels


@pytest.mark.parametrize(('sar','width','height'), [(Fraction(10**8), 16, 16),
                                                   (Fraction(1,10**8), 32, 32),
                                                   (Fraction(4), 4096, 3000)])
def test_invalid_expansion_rejected_before_bgr_allocation(sar, width, height):
    stream = SimpleNamespace(sample_aspect_ratio=sar, codec_context=SimpleNamespace(width=width, height=height))
    frame = SimpleNamespace(to_ndarray=lambda **_: pytest.fail('Should reject unsupported raster before decoding BGR'))
    with pytest.raises(ValueError, match='像素宽高比'):
        display_dimensions(stream)
    with pytest.raises(ValueError, match='像素宽高比'):
        display_bgr(frame, stream)


def test_ae_position_curve_uses_square_pixel_distance_in_rotated_clip(tmp_path):
    from cv.motion_analyzer import analyze_shot_motion
    from recipe.ae_script import build_ae_setup
    from schemas import Shot, TimeRange
    from tests.test_motion_benchmark import benchmark

    source = benchmark.generate_case(tmp_path, 'out_and_back', duration=.5)['video_path']
    tagged = tmp_path/'rotated-pasp.mp4'
    with av.open(str(source)) as original, av.open(str(tagged), 'w') as out:
        src = original.streams.video[0]
        track = out.add_stream_from_template(src)
        track.codec_context.sample_aspect_ratio = Fraction(3, 4)
        track.set_display_rotation(90)
        for packet in original.demux(src):
            if packet.size:
                packet.stream = track
                out.mux(packet)
    meta = read_video_metadata(tagged)
    assert (meta['width'], meta['height']) == (180, 240)
    measured = analyze_shot_motion(tagged, 0, .5, meta['width'], meta['height'])
    shot = Shot(shot_id='sar', time=TimeRange(start=0, end=.5, duration=.5), measured_motion=measured)
    setup = build_ae_setup(shot.model_dump(), width=180, height=240, fps=meta['fps'], padded=True)
    assert (setup['width'], setup['height']) == (180, 240)
    curve, = setup['curves']
    assert curve['property'] == 'position_y'
    values = [p['value'] * 240 / 100 for p in curve['points']]
    # Source's ~63.3-pixel excursion shrinks horizontally by 3/4, then rotates upwards.
    assert min(values) == pytest.approx(-63.3 * .75, abs=1)
    assert abs(values[-1]) < 1
    padding = setup['artwork_padding']
    assert padding['bottom_px'] == 48 and padding['top_px'] <= 1
