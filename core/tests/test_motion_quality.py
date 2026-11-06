import math
import weakref

import numpy as np
import pytest

from cv import motion_analyzer
from cv.motion_analyzer import analyze_shot_motion
from cv.motion_quality import motion_quality
from schemas.measured_motion import MotionSample
from tests.test_cv_motion import _create_test_video_with_motion
from tests.test_motion_benchmark import benchmark


def samples(times, *, position=lambda t, i: (0, 0), scale=lambda t, i: 1,
            rotation=lambda t, i: 0, segment=0):
    return [MotionSample(source_time=t, segment_id=segment, segment_start_time=times[0],
                         translation_x_px=position(t, i)[0], translation_y_px=position(t, i)[1],
                         scale_ratio=scale(t, i), rotation_deg=rotation(t, i),
                         matrix=((1, 0, 0), (0, 1, 0))) for i, t in enumerate(times)]


def quality(points):
    return motion_quality(points, frame_width=640, frame_height=360)


@pytest.mark.parametrize('times', [np.linspace(0, 3, 25), [0, .031, .19, .35, .5, .9, 1, 1.3]])
def test_constant_velocity_is_stable_for_cfr_and_vfr(times):
    points = samples(times, position=lambda t, i: (60 * t, -20 * t),
                     rotation=lambda t, i: .015 * (-1) ** i,
                     scale=lambda t, i: math.exp(.0001 * (-1) ** i))
    stability, shake = quality(points)
    assert stability == pytest.approx(1)
    assert shake == 0


def test_center_zoom_and_constant_rotation_do_not_generate_shake():
    points = samples(np.linspace(0, 3, 25), scale=lambda t, i: 1 + .15 * t,
                     rotation=lambda t, i: 20 * t)
    stability, shake = quality(points)
    assert stability > .98
    assert shake == 0


def test_smooth_eased_turnaround_is_not_severe_shake():
    points = samples(np.linspace(0, 3, 25), position=lambda t, i: (40 * math.sin(math.pi * t / 3), 0))
    stability, shake = quality(points)
    assert stability > .95
    assert shake == 0


@pytest.mark.parametrize('component', ['translation', 'rotation', 'scale'])
def test_repeated_large_alternation_is_shake_evidence(component):
    points = samples(np.linspace(0, 2, 17),
                     position=lambda t, i: (5 * (-1) ** i, 0) if component == 'translation' else (0, 0),
                     rotation=lambda t, i: .6 * (-1) ** i if component == 'rotation' else 0,
                     scale=lambda t, i: math.exp(.006 * (-1) ** i) if component == 'scale' else 1)
    stability, shake = quality(points)
    assert stability < .2
    assert shake > .9


def test_noise_dead_zones_ignore_tiny_alternation_in_inactive_channels():
    points = samples(np.linspace(0, 2, 17), position=lambda t, i: (.15 * (-1) ** i, .1 * (-1) ** i),
                     rotation=lambda t, i: .02 * (-1) ** i,
                     scale=lambda t, i: math.exp(.0002 * (-1) ** i))
    assert quality(points) == (1, 0)


def test_reversal_frequency_depends_on_actual_time_not_pair_count():
    fast = samples(np.linspace(0, 2, 17), position=lambda t, i: (5 * (-1) ** i, 0))
    slow = samples(np.linspace(0, 20, 17), position=lambda t, i: (5 * (-1) ** i, 0))
    assert quality(fast)[1] > .9
    assert quality(slow)[1] == 0


def test_tracking_gap_does_not_create_reversals_between_references():
    first = samples([0, .1, .2], position=lambda t, i: (10 * i, 0))
    second = samples([.8, .9, 1], position=lambda t, i: (-10 * i, 0), segment=1)
    assert quality(first + second) == (1, 0)


def test_empty_or_malformed_trajectory_is_not_silently_high_quality():
    assert quality([]) == (0, 0)
    with pytest.raises(ValueError, match='increase'):
        quality(samples([0, .1, .1]))
    with pytest.raises(ValueError, match='positive'):
        motion_quality([], frame_width=0, frame_height=1)


@pytest.mark.parametrize('motion', ['translation', 'scale'])
def test_real_encoded_smooth_motion_is_stable_and_not_shake(tmp_path, motion):
    path = _create_test_video_with_motion(tmp_path / f'{motion}.mp4', motion)
    measured = analyze_shot_motion(path, 0, 1, 640, 360)
    assert measured.status == 'ok'
    # This older zoom fixture rounds resize/crop coordinates to integer pixels,
    # so its actual encoded path includes small steps rather than an ideal ramp.
    assert measured.stability > .9
    assert measured.shake_score < .05
    assert measured.method.endswith('center_v4')


def test_real_encoded_vfr_combined_transform_is_not_spurious_shake(tmp_path):
    case = benchmark.generate_case(tmp_path, 'variable_pts')
    measured = analyze_shot_motion(case['video_path'], 0, case['end_time'], case['width'], case['height'])
    assert measured.status == 'ok'
    assert measured.stability > .95
    assert measured.shake_score < .05


def test_real_encoded_alternation_remains_strong_shake_evidence(tmp_path):
    case = benchmark.generate_case(tmp_path, 'alternating_shake')
    measured = analyze_shot_motion(case['video_path'], 0, case['end_time'], case['width'], case['height'])
    assert measured.status == 'ok'
    assert measured.stability < .2
    assert measured.shake_score > .9


def _identity_result():
    return dict(valid=True, dx_px=0, dy_px=0, scale_ratio=1, rotation_deg=0,
                inlier_ratio=1, tracked_features=80)


def test_analyzer_streams_with_at_most_two_decoded_arrays_retained(monkeypatch):
    references = []
    closed = []

    def generate(*args, **kwargs):
        try:
            for i in range(300):
                image = np.zeros((20, 20, 3), np.uint8)
                references.append(weakref.ref(image))
                yield {'timestamp': i / 8, 'image': image}
        finally:
            closed.append(True)

    def estimate(*args):
        assert sum(reference() is not None for reference in references) <= 2
        return _identity_result()

    monkeypatch.setattr(motion_analyzer, 'iter_frames_for_cv', generate)
    monkeypatch.setattr(motion_analyzer, 'estimate_transform_between_frames', estimate)
    measured = analyze_shot_motion('unused.mp4', 0, 38, 20, 20)
    assert measured.status == 'ok'
    assert measured.sample_count == 300 and measured.total_pair_count == 299
    assert len(measured.trajectory) == 300
    assert closed == [True]
    assert all(reference() is None for reference in references)


def test_stream_sampling_failure_closes_generator_and_returns_failed(monkeypatch):
    closed = []

    def generate(*args, **kwargs):
        try:
            for i in range(2):
                yield {'timestamp': i / 8, 'image': np.zeros((20, 20, 3), np.uint8)}
            raise RuntimeError('corrupt frame')
        finally:
            closed.append(True)

    monkeypatch.setattr(motion_analyzer, 'iter_frames_for_cv', generate)
    monkeypatch.setattr(motion_analyzer, 'estimate_transform_between_frames', lambda *args: _identity_result())
    measured = analyze_shot_motion('unused.mp4', 0, 1, 20, 20)
    assert measured.status == 'failed'
    assert measured.sample_count == 2
    assert 'corrupt frame' in measured.message
    assert measured.trajectory == [] and measured.confidence == 0
    assert closed == [True]


def test_transform_exception_also_closes_stream(monkeypatch):
    closed = []

    def generate(*args, **kwargs):
        try:
            for i in range(3):
                yield {'timestamp': i / 8, 'image': np.zeros((20, 20, 3), np.uint8)}
        finally:
            closed.append(True)

    def fail(*args):
        raise RuntimeError('transform failed')

    monkeypatch.setattr(motion_analyzer, 'iter_frames_for_cv', generate)
    monkeypatch.setattr(motion_analyzer, 'estimate_transform_between_frames', fail)
    with pytest.raises(RuntimeError, match='transform failed'):
        analyze_shot_motion('unused.mp4', 0, 1, 20, 20)
    assert closed == [True]


@pytest.mark.parametrize('count', [0, 1])
def test_stream_with_too_few_frames_is_failed(monkeypatch, count):
    monkeypatch.setattr(motion_analyzer, 'iter_frames_for_cv', lambda *a, **kw: iter([
        {'timestamp': 0, 'image': np.zeros((20, 20, 3), np.uint8)} for _ in range(count)]))
    measured = analyze_shot_motion('unused.mp4', 0, 1, 20, 20)
    assert measured.status == 'failed' and measured.sample_count == count
