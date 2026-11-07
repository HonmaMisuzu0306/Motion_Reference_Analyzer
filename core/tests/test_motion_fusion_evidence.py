"""Motion labels use comparable units and every observed point in a valid trajectory."""
import json

import pytest

from cv.motion_fusion import fuse_motion
from schemas.measured_motion import MeasuredMotion, MotionSample


def trajectory(values, field='translation_x_ratio'):
    samples = []
    for index, value in enumerate(values):
        params = {field: value}
        samples.append(MotionSample(source_time=index / 4, segment_id=0, segment_start_time=0,
                                    matrix=((1, 0, 0), (0, 1, 0)), **params))
    return samples


@pytest.mark.parametrize('measurements,expected', [
    ({'scale_change_percent': 1.1, 'translation_x_ratio': .12}, 'pan_right'),
    ({'scale_change_percent': 5, 'translation_y_ratio': -.1}, 'tilt_up'),
    ({'scale_change_percent': 2, 'translation_x_ratio': -.015}, 'push_in'),
    ({'rotation_deg': -4, 'translation_x_ratio': .02}, 'rotation'),
    ({'scale_change_percent': -3, 'translation_x_ratio': .02}, 'pull_out'),
])
def test_dominant_motion_compares_threshold_normalized_amplitudes(measurements, expected):
    result = fuse_motion({}, MeasuredMotion(confidence=.85, **measurements))
    assert result['measured_type'] == result['fused_type'] == expected


@pytest.mark.parametrize('field,values', [
    ('translation_x_ratio', [0, .08, 0]),
    ('translation_y_ratio', [0, -.05, 0]),
    ('scale_ratio', [1, 1.08, 1]),
    ('rotation_deg', [0, 5, 0]),
])
def test_returning_to_start_is_not_static(field, values):
    measured = MeasuredMotion(confidence=.9, trajectory_status='complete', trajectory=trajectory(values, field))
    result = fuse_motion({}, measured)
    assert result['measured_type'] == result['fused_type'] == 'complex'


def test_minor_jitter_does_not_turn_directional_motion_into_complex():
    measured = MeasuredMotion(confidence=.9, trajectory_status='complete',
                              trajectory=trajectory([0, .04, .039, .08, .079, .12]))
    assert fuse_motion({}, measured)['measured_type'] == 'pan_right'


def test_subthreshold_trajectory_remains_static():
    measured = MeasuredMotion(confidence=.9, trajectory_status='complete',
                              trajectory=trajectory([0, .001, -.001, 0]))
    assert fuse_motion({}, measured)['measured_type'] == 'static'


def test_rotation_branch_wrap_does_not_look_like_reversal():
    measured = MeasuredMotion(confidence=.9, trajectory_status='complete',
                              trajectory=trajectory([0, 90, 179, -179, -170], 'rotation_deg'))
    assert fuse_motion({}, measured)['measured_type'] == 'rotation'


@pytest.mark.parametrize('changes', [
    {'trajectory_status': 'partial'}, {'status': 'incomplete_tracking'}, {'confidence': .2},
])
def test_incomplete_or_low_confidence_measurements_are_not_definitive(changes):
    measured = MeasuredMotion(confidence=.9, translation_x_ratio=.1)
    measured = measured.model_copy(update=changes)
    result = fuse_motion({'type': 'pan_right', 'confidence': .8}, measured)
    assert result['measured_type'] == 'unknown'
    assert result['fused_type'] == 'pan_right'
    assert result['fused_confidence'] < .8
    assert result['conflict'] is False


@pytest.mark.parametrize('kind', ['empty', 'single', 'duplicate_time', 'multiple_segments'])
def test_malformed_complete_trajectory_does_not_imply_static(kind):
    samples = trajectory([0, .1, 0])
    if kind == 'empty':
        samples = []
    elif kind == 'single':
        samples = samples[:1]
    elif kind == 'duplicate_time':
        samples[1] = samples[1].model_copy(update={'source_time': 0})
    else:
        samples[-1] = samples[-1].model_copy(update={'segment_id': 1})
    measured = MeasuredMotion(confidence=.9, trajectory_status='complete', trajectory=samples)
    assert fuse_motion({}, measured)['measured_type'] == 'unknown'


def test_legacy_confident_summary_keeps_agreement_and_conflict_contract():
    measured = MeasuredMotion(scale_change_percent=7.2, confidence=.8)
    agreement = fuse_motion({'type': 'push_in', 'confidence': .82}, measured)
    assert agreement['measured_type'] == agreement['fused_type'] == 'push_in'
    assert agreement['fused_confidence'] > .82 and not agreement['conflict']
    conflict = fuse_motion({'type': 'static', 'confidence': .9}, measured)
    assert conflict['conflict'] and conflict['semantic_type'] == 'static'
    assert conflict['measured_type'] == 'push_in'


@pytest.mark.parametrize('confidence', [None, float('nan'), float('inf'), 'invalid'])
def test_invalid_legacy_semantic_confidence_never_leaks_nonfinite_json(confidence):
    result = fuse_motion({'type': 'unknown', 'confidence': confidence}, MeasuredMotion())
    assert result['semantic_confidence'] == result['fused_confidence'] == 0
    assert result['measured_type'] == 'unknown'
    json.dumps(result, allow_nan=False)
