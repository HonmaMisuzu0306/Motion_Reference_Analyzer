"""Encoded adversarial cuts distinguish continuous motion, flashes and short edits."""
from fractions import Fraction

import av
import cv2
import numpy as np
import pytest

from selection.media import detect_range_scenes
from video import scene_features
from video.scene_detect import detect_scenes
from video.scene_features import SceneBoundaryDetector

FPS = 24


def texture(seed=41, width=192, height=128):
    rng = np.random.default_rng(seed)
    blocks = rng.integers(20, 236, (8, 12, 3), dtype=np.uint8)
    return cv2.resize(blocks, (width, height), interpolation=cv2.INTER_NEAREST)


def write_frames(path, frames, origin=0):
    h, w = frames[0].shape[:2]
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=FPS)
        stream.width, stream.height, stream.pix_fmt = w, h, 'yuv420p'
        stream.options = {'crf': '18'}
        for i, pixels in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(pixels, format='bgr24')
            frame.pts, frame.time_base = i + origin * FPS, Fraction(1, FPS)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return path


def cuts(path, duration):
    return ([shot['start'] for shot in detect_scenes(path)[1:]],
            [shot.start for shot in detect_range_scenes(path, 0, duration)[1:]])


@pytest.mark.parametrize('size', [(192, 128), (16, 16)])
def test_cross_content_cut_survives_motion_filter(tmp_path, size):
    a, b = [texture(seed, *size) for seed in (41, 76)]
    path = write_frames(tmp_path / 'content.mp4', [a] * 24 + [b] * 24)
    for result in cuts(path, 2):
        assert result == pytest.approx([1], abs=.001)


@pytest.mark.parametrize('color', [(255, 255, 255), (0, 0, 0), (0, 0, 255)])
def test_single_white_black_or_colored_flash_does_not_split_scene(tmp_path, color):
    a = texture()
    flash = np.full_like(a, color)
    path = write_frames(tmp_path / 'flash.mp4', [a] * 24 + [flash] + [a] * 23)
    for result in cuts(path, 2):
        assert result == []


@pytest.mark.parametrize('origin', [0, 10])
def test_two_frame_bright_insert_remains_two_real_cuts(tmp_path, origin):
    a = texture()
    b = np.full_like(a, 255)
    path = write_frames(tmp_path / 'short-shot.mp4', [a] * 20 + [b] * 2 + [a] * 26, origin=origin)
    for result in cuts(path, 2):
        assert result == pytest.approx([20 / FPS, 22 / FPS], abs=.001)
    filtered = detect_scenes(path, min_shot_duration=.5)
    assert [shot['start'] for shot in filtered[1:]] == pytest.approx([20 / FPS], abs=.001)


@pytest.mark.parametrize('origin', [0, 10])
def test_flash_between_different_scenes_marks_first_observable_change(tmp_path, origin):
    a, b = texture(), texture(76)
    path = write_frames(tmp_path / 'flash-cut.mp4', [a] * 24 + [np.full_like(a, 255)] + [b] * 23, origin=origin)
    for result in cuts(path, 2):
        # Frame 24 is the flash; frame 25 is B. The cut cannot be timed inside an opaque flash.
        assert result == pytest.approx([1], abs=.001)
    selected = detect_range_scenes(path, .75, 1.25)
    assert [(shot.start, shot.end) for shot in selected] == [(.75, 1), (1, 1.25)]


def test_isolated_crop_jump_is_not_accepted_as_continuous_pan(tmp_path):
    a = texture()
    b = np.roll(a, 8, axis=1)
    path = write_frames(tmp_path / 'crop-cut.mp4', [a] * 24 + [b] * 24)
    for result in cuts(path, 2):
        assert result == pytest.approx([1], abs=.001)


def test_half_open_range_does_not_borrow_flash_confirmation_from_outside(tmp_path):
    a = texture()
    path = write_frames(tmp_path / 'edge-flash.mp4', [a] * 24 + [np.full_like(a, 255)] + [a] * 23)
    # The return to A is excluded, so the flash cannot yet be identified as transient.
    end = 1 + 1 / FPS
    assert [shot.start for shot in detect_range_scenes(path, .75, end)[1:]] == [1]
    assert [shot.start for shot in detect_range_scenes(path, .75, end + 1 / FPS)[1:]] == []
    # Starting on the flash also removes the earlier A evidence.
    assert [shot.start for shot in detect_range_scenes(path, 1, 1.25)[1:]] == pytest.approx([end])


@pytest.mark.parametrize('size', [8, 16, 64])
def test_sustained_color_change_is_not_a_flash_even_for_tiny_video(tmp_path, size):
    red = np.full((size, size, 3), (0, 0, 255), np.uint8)
    green = np.full((size, size, 3), (0, 255, 0), np.uint8)
    path = write_frames(tmp_path / 'color-cut.mp4', [red] * 24 + [green] * 24)
    for result in cuts(path, 2):
        assert result == pytest.approx([1], abs=.001)


def test_single_frame_range_does_not_invent_an_internal_cut(tmp_path):
    path = write_frames(tmp_path / 'one-frame.mp4', [texture()] * 4)
    selected = detect_range_scenes(path, 0, 1 / FPS)
    assert [(shot.start, shot.end) for shot in selected] == [(0, 1 / FPS)]


def test_detector_rejects_non_monotonic_time_and_finishes_once():
    detector = SceneBoundaryDetector()
    detector.push(0, texture())
    with pytest.raises(ValueError, match='递增'):
        detector.push(0, texture())
    detector.push(1, texture(76))
    assert detector.finish() == [1]
    assert detector.finish() == []
    with pytest.raises(ValueError, match='结束'):
        detector.push(2, texture())


def test_continuous_vfr_pan_uses_velocity_not_per_frame_displacement(tmp_path):
    path = tmp_path / 'vfr-pan.mp4'
    times = [0, .04, .16, .20, .32, .36, .48, .52]
    world = texture(width=384)
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=25)
        stream.width, stream.height, stream.pix_fmt = 192, 128, 'yuv420p'
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1000)
        for timestamp in times:
            offset = round(timestamp * 100)
            frame = av.VideoFrame.from_ndarray(world[:, offset:offset + 192].copy(), format='bgr24')
            frame.pts, frame.time_base = round(timestamp * 1000), Fraction(1, 1000)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    assert len(detect_scenes(path)) == 1
    assert len(detect_range_scenes(path, 0, .56)) == 1


def test_low_change_sequence_never_estimates_motion(monkeypatch):
    monkeypatch.setattr(scene_features, '_motion', lambda *_: pytest.fail('unexpected motion estimation'))
    detector = SceneBoundaryDetector()
    a = texture()
    for i in range(240):
        assert detector.push(i / FPS, a + i % 3) == []
    assert detector.finish() == []


@pytest.mark.parametrize('levels', [[0, 2, 40], [0, 40, 42]])
def test_low_change_neighbor_can_confirm_candidate_in_either_direction(monkeypatch, levels):
    calls = []

    def unit_motion(before, current):
        calls.append((before.time, current.time))
        return scene_features._Motion(np.ones((5, 2)), current.time - before.time)

    monkeypatch.setattr(scene_features, '_motion', unit_motion)
    detector = SceneBoundaryDetector()
    for i, level in enumerate(levels):
        assert detector.push(i, np.full((64, 64, 3), level, dtype=np.uint8)) == []
    assert detector.finish() == []
    assert sorted(calls) == [(0, 1), (1, 2)]
