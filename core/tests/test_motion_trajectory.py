from itertools import cycle

import numpy as np
import pytest
from pydantic import ValidationError

from cv import motion_analyzer
from cv.frame_sampler import sample_frames_for_cv
from cv.motion_analyzer import analyze_shot_motion
from cv.trajectory import compose_trajectory
from schemas.measured_motion import FramePairTransform, MeasuredMotion
from tests.test_cv_motion import _create_test_video_with_motion


def pair(start, end, **kwargs):
    return FramePairTransform(start_time=start, end_time=end, valid=True, **kwargs)


def compose(pairs):
    return compose_trajectory(pairs, analysis_width=100, analysis_height=100,
                              original_width=200, original_height=200)


def test_center_zoom_has_no_spurious_position_animation():
    values = compose([pair(12, 12.25, scale_ratio=1.1, dx_px=-5, dy_px=-5),
                      pair(12.25, 12.5, scale_ratio=1.1, dx_px=-5, dy_px=-5)])
    assert values[-1].scale_ratio == pytest.approx(1.21)
    assert values[-1].translation_x_px == pytest.approx(0, abs=1e-10)
    assert values[-1].translation_y_px == pytest.approx(0, abs=1e-10)
    assert [p.source_time for p in values] == [12, 12.25, 12.5]


def test_translation_is_rotated_by_the_next_transform_in_original_coordinates():
    # Rotate clockwise 90 degrees about (50,50) after translating 10 analysis pixels.
    values = compose([pair(0, .1, dx_px=10), pair(.1, .2, rotation_deg=90, dx_px=100)])
    assert values[-1].translation_x_px == pytest.approx(0, abs=1e-10)
    assert values[-1].translation_y_px == pytest.approx(20)
    assert values[-1].rotation_deg == 90
    assert np.asarray(values[-1].matrix) @ [100, 100, 1] == pytest.approx([100, 120])


def test_invalid_pair_breaks_reference_frame_instead_of_bridging_gap():
    values = compose([pair(0, .1, dx_px=10), FramePairTransform(start_time=.1, end_time=.2),
                      pair(.2, .3, dx_px=5)])
    assert [p.segment_id for p in values] == [0, 0, 1, 1]
    assert [p.translation_x_px for p in values] == pytest.approx([0, 20, 0, 10])
    assert values[-1].segment_start_time == .2


def test_rotation_stays_unwrapped_beyond_180_degrees():
    values = compose([pair(0, 1, rotation_deg=100), pair(1, 2, rotation_deg=100)])
    assert values[-1].rotation_deg == 200


def test_out_of_order_pairs_and_nonfinite_measurements_are_rejected():
    with pytest.raises(ValueError, match='倒退'):
        compose([pair(1, 2), pair(.5, 1)])
    for value in [float('nan'), float('inf'), -float('inf')]:
        with pytest.raises(ValidationError):
            FramePairTransform(dx_px=value)
        with pytest.raises(ValidationError):
            MeasuredMotion(scale_ratio=value)


def test_real_cv_keeps_last_half_open_frame_and_actual_pts(tmp_path):
    path = _create_test_video_with_motion(tmp_path / 'move.mp4', 'translation')
    frames = sample_frames_for_cv(path, 0, 1, target_fps=24)
    assert frames[1]['timestamp'] == pytest.approx(1 / 24, abs=1e-12)
    measured = analyze_shot_motion(path, 0, 1, 640, 360)
    assert measured.status == 'ok' and measured.trajectory_status == 'complete'
    assert measured.translation_reference == 'frame_center'
    assert measured.trajectory[-1].source_time == pytest.approx(23 / 24, abs=1e-12)
    assert all(p.source_time < 1 for p in measured.trajectory)
    assert measured.translation_x_px == pytest.approx(20, abs=2)
    assert measured.translation_y_px == pytest.approx(-10, abs=2)


def test_real_center_zoom_does_not_invent_pan(tmp_path):
    path = _create_test_video_with_motion(tmp_path / 'zoom.mp4', 'scale')
    measured = analyze_shot_motion(path, 0, 1, 640, 360)
    assert measured.status == 'ok'
    assert measured.scale_change_percent == pytest.approx(10, abs=2)
    assert abs(measured.translation_x_px) < 2
    assert abs(measured.translation_y_px) < 2


def test_tracking_gap_does_not_publish_a_complete_global_measurement(monkeypatch):
    frames = [{'timestamp': i / 10, 'image': np.zeros((100, 100, 3), np.uint8)} for i in range(4)]
    monkeypatch.setattr(motion_analyzer, 'iter_frames_for_cv', lambda *a, **kw: iter(frames))
    results = cycle([
        dict(valid=valid, dx_px=5, dy_px=0, scale_ratio=1, rotation_deg=0,
             inlier_ratio=.9, tracked_features=50) for valid in (True, False, True)])
    monkeypatch.setattr(motion_analyzer, 'estimate_transform_between_frames', lambda *a: next(results))
    measured = analyze_shot_motion('unused.mp4', 0, 1, 100, 100)
    assert measured.status == 'incomplete_tracking'
    assert measured.trajectory_status == 'partial'
    assert measured.confidence == 0
    assert len({p.segment_id for p in measured.trajectory}) == 2
