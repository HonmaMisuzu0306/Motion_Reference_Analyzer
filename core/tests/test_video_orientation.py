"""Pixel-level orientation contracts for the actual container/decoder pipeline."""
from fractions import Fraction

import av
import numpy as np
import pytest

from video.frame_sampler import sample_frames
from video.metadata import read_video_metadata
from video.orientation import display_bgr
from video.playback import playback_source


def oriented_movie(path, angle=0, reflected=False, *, shifted=False, matrix=None, sar=None):
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=24)
        stream.width, stream.height, stream.pix_fmt = 48, 32, 'yuv420p'
        if sar is not None:
            stream.codec_context.sample_aspect_ratio = sar
        if matrix is None:
            stream.set_display_rotation(angle, hflip=reflected)
        else:
            stream.set_display_matrix(matrix)
        y, x = np.indices((32, 48))
        image = np.stack([x * 5, y * 7, (x * 13 + y * 11) % 256], axis=-1).astype(np.uint8)
        for i in range(3):
            frame = av.VideoFrame.from_ndarray(image, format='bgr24')
            frame.pts, frame.time_base = (240 if shifted else 0) + i, Fraction(1, 24)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return path


@pytest.mark.parametrize('angle', [0, 90, 180, 270])
@pytest.mark.parametrize('reflected', [False, True])
def test_tagged_track_matches_decoded_pixels_and_dimensions(tmp_path, angle, reflected):
    src = oriented_movie(tmp_path/'track.mp4', angle, reflected)
    with av.open(str(src)) as container:
        stream = container.streams.video[0]
        frame = next(container.decode(stream))
        expected = np.rot90(frame.to_ndarray(format='bgr24'), k=angle//90)
        if reflected:
            expected = expected[:, ::-1]
        actual = display_bgr(frame, stream)
        assert actual.flags.c_contiguous
        np.testing.assert_array_equal(actual, expected)
    meta = read_video_metadata(src)
    assert (meta['height'], meta['width']) == expected.shape[:2]
    np.testing.assert_array_equal(sample_frames(src, 0, .1, 1)[0]['image'], actual)


def test_remux_of_offset_track_preserves_its_mirrored_rotation(tmp_path):
    src = oriented_movie(tmp_path/'rotated.mp4', 90, True, shifted=True)
    preview = playback_source(src, tmp_path/'preview')
    assert preview != src
    with av.open(str(src)) as original, av.open(str(preview)) as remuxed:
        s, r = original.streams.video[0], remuxed.streams.video[0]
        matrix = s.codec_context.coded_side_data['display_matrix']
        assert r.codec_context.coded_side_data.get('display_matrix') == matrix


def test_nonorthogonal_track_has_an_actionable_import_error(tmp_path):
    matrix = [65536, 0, 0, 8192, 65536, 0, 0, 0, 1 << 30]
    src = oriented_movie(tmp_path/'skewed.mp4', matrix=matrix)
    with pytest.raises(ValueError, match='显示矩阵'):
        read_video_metadata(src)


def test_absent_frame_matrix_falls_back_to_track_and_conflict_is_rejected(tmp_path):
    from types import SimpleNamespace

    src = oriented_movie(tmp_path/'rotated.mp4', 90)
    identity = oriented_movie(tmp_path/'normal.mp4', 0)
    with av.open(str(src)) as first, av.open(str(identity)) as second:
        stream = first.streams.video[0]
        frame = next(first.decode(stream))
        no_side = SimpleNamespace(side_data={}, to_ndarray=frame.to_ndarray)
        np.testing.assert_array_equal(display_bgr(no_side, stream), np.rot90(frame.to_ndarray(format='bgr24')))
        with pytest.raises(ValueError, match='帧显示方向'):
            display_bgr(frame, second.streams.video[0])
