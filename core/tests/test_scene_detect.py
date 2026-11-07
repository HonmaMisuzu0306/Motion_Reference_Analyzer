"""Hard cuts with the same average color must retain their spatial evidence."""
from fractions import Fraction

import av
import numpy as np
import pytest

from selection.media import detect_range_scenes
from video.scene_detect import detect_scenes


def write_layout_video(path, *, size=64, origin=0, cut=True):
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=24)
        stream.width = stream.height = size
        stream.pix_fmt = 'yuv420p'
        for i in range(48):
            frame = np.full((size, size, 3), 20, np.uint8)
            frame[:, :size // 2] = 220
            if cut and i >= 24:
                frame = frame[:, ::-1].copy()
            image = av.VideoFrame.from_ndarray(frame, format='bgr24')
            image.pts, image.time_base = i + origin * 24, Fraction(1, 24)
            for packet in stream.encode(image):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return path


@pytest.mark.parametrize('origin', [0, 10])
def test_same_color_layout_cut_is_found_in_both_pipelines(tmp_path, origin):
    path = write_layout_video(tmp_path / 'layout.mp4', origin=origin)
    full = detect_scenes(path)
    assert [(shot['start'], shot['end']) for shot in full] == [(0, 1), (1, 2)]
    selected = detect_range_scenes(path, .75, 1.25)
    assert [(shot.start, shot.end) for shot in selected] == [(.75, 1), (1, 1.25)]


@pytest.mark.parametrize('size', [8, 64])
def test_static_and_tiny_video_do_not_fail_or_invent_cuts(tmp_path, size):
    path = write_layout_video(tmp_path / 'static.mp4', size=size, cut=False)
    assert [(shot['start'], shot['end']) for shot in detect_scenes(path)] == [(0, 2)]
    assert len(detect_range_scenes(path, .25, 1.75)) == 1


def test_cut_at_selection_boundary_does_not_create_empty_shot(tmp_path):
    path = write_layout_video(tmp_path / 'edge.mp4')
    assert [(shot.start, shot.end) for shot in detect_range_scenes(path, 0, 1)] == [(0, 1)]
    assert [(shot.start, shot.end) for shot in detect_range_scenes(path, 1, 2)] == [(1, 2)]
