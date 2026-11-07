"""Encoded continuous rotation/zoom must not become one-frame shots."""
import cv2
import pytest

from selection.media import detect_range_scenes
from tests.test_scene_motion import FPS, cuts, texture, write_frames
from video.scene_features import SceneBoundaryDetector


def transformed_frames(angle_step=0, zoom_step=0, cut_at=None, jump=False, border=cv2.BORDER_REFLECT_101):
    frames = []
    for i in range(48):
        source = texture(76 if cut_at is not None and i >= cut_at else 41)
        source = (source > 128).astype('uint8') * 255
        phase = (24 if i >= 24 else 0) if jump else i
        matrix = cv2.getRotationMatrix2D((96, 64), phase * angle_step, 1 + phase * zoom_step)
        frames.append(cv2.warpAffine(source, matrix, (192, 128), borderMode=border))
    return frames


@pytest.mark.parametrize('border', [cv2.BORDER_REFLECT_101, cv2.BORDER_CONSTANT])
@pytest.mark.parametrize('angle,zoom', [(2, 0), (-2, 0), (0, .04), (1.5, .006)])
def test_continuous_rotation_and_zoom_remain_one_shot(tmp_path, angle, zoom, border):
    path = write_frames(tmp_path / 'continuous.mp4', transformed_frames(angle, zoom, border=border))
    for result in cuts(path, 2):
        assert result == []
    assert len(detect_range_scenes(path, .25, 1.75)) == 1


def test_real_content_cut_during_rotation_is_preserved(tmp_path):
    path = write_frames(tmp_path / 'rotating-cut.mp4', transformed_frames(2, cut_at=24))
    for result in cuts(path, 2):
        assert result == pytest.approx([1], abs=1 / FPS)


@pytest.mark.parametrize('angle,zoom', [(.5, 0), (0, .006)])
def test_isolated_rotation_or_zoom_jump_is_still_a_cut(tmp_path, angle, zoom):
    path = write_frames(tmp_path / 'jump.mp4', transformed_frames(angle, zoom, jump=True))
    for result in cuts(path, 2):
        assert result == pytest.approx([1], abs=.001)


def test_three_frame_content_insert_during_rotation_is_preserved(tmp_path):
    frames = transformed_frames(2)
    other = transformed_frames(2, cut_at=0)
    frames[24:27] = other[24:27]
    path = write_frames(tmp_path / 'rotation-insert.mp4', frames)
    for result in cuts(path, 2):
        assert result == pytest.approx([1, 27 / FPS], abs=.001)


def test_rotation_continuity_uses_elapsed_time_for_vfr():
    detector = SceneBoundaryDetector()
    source = (texture() > 128).astype('uint8') * 255
    cuts_found = []
    for timestamp in [0, .04, .10, .14, .20, .24, .30, .34]:
        matrix = cv2.getRotationMatrix2D((96, 64), timestamp * 48, 1)
        frame = cv2.warpAffine(source, matrix, (192, 128), borderMode=cv2.BORDER_REFLECT_101)
        cuts_found += detector.push(timestamp, frame)
    assert cuts_found + detector.finish() == []
