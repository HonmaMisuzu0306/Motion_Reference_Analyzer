import json

import numpy as np
import pytest

from cv.trajectory import compose_trajectory
from recipe.ae_recipe import generate_ae_recipe
from recipe.curves import animation_curves, complete_trajectory, simplify_curve
from schemas import Shot, TimeRange
from schemas.measured_motion import FramePairTransform, MeasuredMotion, MotionSample


def measured_shot(values, times, start=12, end=14):
    samples = [MotionSample(
        source_time=time, segment_id=0, segment_start_time=times[0], translation_x_ratio=value,
        translation_x_px=value * 100, matrix=((1, 0, value * 100), (0, 1, 0)))
        for time, value in zip(times, values)]
    motion = MeasuredMotion(
        status='ok', confidence=.9, trajectory_status='complete', translation_reference='frame_center',
        frame_width=100, frame_height=100, trajectory=samples, sample_count=len(samples),
        valid_pair_count=len(samples) - 1, total_pair_count=len(samples) - 1,
        translation_x_ratio=values[-1], translation_x_px=values[-1] * 100,
    )
    return Shot(shot_id='test', time=TimeRange(start=start, end=end, duration=end - start),
                measured_motion=motion).model_dump()


def test_linear_curve_simplification_uses_time_not_sample_index():
    points = [(12, 0), (12.05, .5), (12.35, 3.5), (12.9, 9)]
    assert simplify_curve(points, .01) == [points[0], points[-1]]


def test_acceleration_and_reversal_preserve_intermediate_keyframes():
    assert len(simplify_curve([(0, 0), (.5, .25), (1, 1)], .01)) == 3
    shot = measured_shot([0, .1, 0], [12.1, 12.5, 13.5])
    recipe = generate_ae_recipe(shot)
    assert recipe['transform']['position_x']['from'] == recipe['transform']['position_x']['to'] == 0
    assert recipe['transform']['position_x']['max_value'] == 10
    plan = recipe['animation_plan']
    assert not any('保持静止' in note for note in plan['notes'])
    curve = plan['curves'][0]
    assert curve['property'] == 'position_x'
    assert [point['value'] for point in curve['points']] == [0, 10, 0]
    assert [point['time'] for point in curve['points']] == pytest.approx([.1, .5, 1.5])
    assert (plan['coverage_start'], plan['coverage_end']) == (12.1, 13.5)
    assert plan['keyframes'][0]['end_time'] == 1.5  # no invented point at shot end 2s
    json.dumps(recipe, allow_nan=False)


def test_every_reconstructed_sample_stays_within_declared_tolerance():
    times = np.linspace(0, 5, 121)
    values = np.sin(times * 3) * 2 + times ** 2 / 4
    reduced = simplify_curve(list(zip(times, values)), .05)
    rebuilt = np.interp(times, [t for t, _ in reduced], [v for _, v in reduced])
    assert np.max(np.abs(values - rebuilt)) <= .05 + 1e-12
    assert len(reduced) < len(times)


@pytest.mark.parametrize('mutate', ['gap', 'bad_reference', 'wrong_count', 'out_of_order'])
def test_inconsistent_trajectory_never_generates_measured_curves(mutate):
    shot = measured_shot([0, .03, .06], [12, 12.5, 13.5])
    measured = shot['measured_motion']
    if mutate == 'gap':
        measured['trajectory_status'] = 'partial'
    elif mutate == 'bad_reference':
        measured['trajectory'][1]['segment_id'] = 1
    elif mutate == 'wrong_count':
        measured['valid_pair_count'] = 9
    else:
        measured['trajectory'][2]['source_time'] = 12.2
    plan = generate_ae_recipe(shot)['animation_plan']
    assert plan['curves'] == []
    assert plan['evidence_source'] == 'insufficient'


def test_trajectory_outside_shot_is_not_silently_clipped_or_extrapolated():
    shot = measured_shot([0, .05, .1], [12, 13, 14.5])
    plan = generate_ae_recipe(shot)['animation_plan']
    assert plan['curves'] == [] and plan['keyframes'] == []
    assert plan['coverage_start'] is None


def test_nonfinite_legacy_values_are_unknown_and_export_remains_strict_json():
    shot = measured_shot([0, .03, .06], [12, 12.5, 13.5])
    shot['measured_motion']['scale_change_percent'] = float('nan')
    recipe = generate_ae_recipe(shot)
    assert recipe['measured_motion']['scale_change_percent'] is None
    assert recipe['animation_plan']['curves'] == []
    assert any('未知' in note for note in recipe['animation_plan']['notes'])
    json.dumps(recipe, allow_nan=False)


@pytest.mark.parametrize('field', [
    'translation_x_px', 'translation_y_px', 'translation_x_ratio', 'translation_y_ratio',
    'scale_ratio', 'rotation_deg', 'matrix', 'first_matrix', 'summary', 'pairs', 'dimensions',
])
def test_redundant_trajectory_evidence_must_agree(field):
    shot = measured_shot([0, .03, .06], [12, 12.5, 13.5])
    measured = shot['measured_motion']
    if field == 'matrix':
        measured['trajectory'][1]['matrix'] = ((1, 0, 4), (0, 1, 0))
    elif field == 'first_matrix':
        # A shear fixing the center still cannot be the identity reference frame.
        measured['trajectory'][0]['matrix'] = ((1, .1, -5), (0, 1, 0))
    elif field == 'summary':
        measured['translation_x_ratio'] = -.6
    elif field == 'pairs':
        measured['pairs'] = [FramePairTransform(start_time=12, end_time=12.5, valid=False).model_dump(),
                             FramePairTransform(start_time=12.5, end_time=13.5, valid=True).model_dump()]
    elif field == 'dimensions':
        measured['frame_width'] = 10 ** 1000
    else:
        measured['trajectory'][1][field] += .1
    assert complete_trajectory(measured) == []
    plan = generate_ae_recipe(shot)['animation_plan']
    assert plan['curves'] == [] and plan['evidence_source'] == 'insufficient'


def test_multiaxis_curves_accept_analyzer_rounding_and_original_coordinate_conversion():
    pairs = [FramePairTransform(start_time=12 + i / 2, end_time=12 + (i + 1) / 2,
                                valid=True, dx_px=1.2345, dy_px=-2.3456,
                                scale_ratio=1.012345, rotation_deg=17.12345) for i in range(3)]
    # Integer resize dimensions need not have exactly equal x/y scale factors.
    points = compose_trajectory(pairs, analysis_width=720, analysis_height=405,
                                original_width=1921, original_height=1081)
    last = points[-1]
    measured = MeasuredMotion(
        status='ok', confidence=.9, trajectory_status='complete', translation_reference='frame_center',
        frame_width=1921, frame_height=1081, trajectory=points, sample_count=4,
        valid_pair_count=3, total_pair_count=3, pairs=pairs,
        translation_x_px=round(last.translation_x_px, 2), translation_y_px=round(last.translation_y_px, 2),
        translation_x_ratio=round(last.translation_x_ratio, 4), translation_y_ratio=round(last.translation_y_ratio, 4),
        scale_ratio=round(last.scale_ratio, 4), scale_change_percent=round((last.scale_ratio - 1) * 100, 2),
        rotation_deg=round(last.rotation_deg, 2),
    ).model_dump()
    curves = animation_curves(measured, 12, 14)
    assert {curve['property'] for curve in curves} == {'position_x', 'position_y', 'global_scale', 'rotation'}
    for curve in curves:
        assert curve['points'][0]['time'] == 0
        assert curve['points'][-1]['time'] == 1.5
    json.dumps(curves, allow_nan=False)


def test_unwrapped_rotation_keeps_multiple_turns():
    pairs = [FramePairTransform(start_time=i, end_time=i + 1, valid=True, rotation_deg=120) for i in range(4)]
    points = compose_trajectory(pairs, analysis_width=100, analysis_height=100,
                                original_width=100, original_height=100)
    last = points[-1]
    measured = MeasuredMotion(
        status='ok', confidence=.9, trajectory_status='complete', translation_reference='frame_center',
        frame_width=100, frame_height=100, trajectory=points, sample_count=5,
        valid_pair_count=4, total_pair_count=4, rotation_deg=480,
        translation_x_px=last.translation_x_px, translation_y_px=last.translation_y_px,
        translation_x_ratio=last.translation_x_ratio, translation_y_ratio=last.translation_y_ratio,
    ).model_dump()
    rotation = next(curve for curve in animation_curves(measured, 0, 5) if curve['property'] == 'rotation')
    assert rotation['points'] == [{'time': 0, 'value': 0}, {'time': 4, 'value': 480}]


@pytest.mark.parametrize('start,end', [(float('nan'), 14), (12, float('inf')), (14, 12), (-1, 14), (12, 12)])
def test_curve_entrypoint_rejects_invalid_source_interval(start, end):
    measured = measured_shot([0, .03, .06], [12, 12.5, 13.5])['measured_motion']
    assert animation_curves(measured, start, end) == []


def test_shot_end_is_exclusive_and_invalid_coverage_has_no_trial_timing_note():
    shot = measured_shot([0, .03, .06], [12, 12.5, 14])
    plan = generate_ae_recipe(shot)['animation_plan']
    assert plan['curves'] == [] and plan['keyframes'] == []
    assert not any('关键帧时间为试作安排' in note for note in plan['notes'])


def test_simplification_does_not_overflow_finite_time_or_value_ranges():
    points = [(-1e308, 0), (0, 15), (1e308, 20)]
    assert simplify_curve(points, .1) == points
    points = [(0, -1e308), (.5, 0), (1, 1e308)]
    assert simplify_curve(points, .1) == [points[0], points[-1]]


@pytest.mark.parametrize('points,tolerance', [
    ([(0, 1), (0, 2)], .1), ([(1, 1), (0, 2)], .1),
    ([(0, float('nan'))], .1), ([(float('inf'), 1)], .1),
    ([(0, 1)], 0), ([(0, 1)], float('nan')),
])
def test_invalid_simplification_input_is_rejected(points, tolerance):
    with pytest.raises(ValueError):
        simplify_curve(points, tolerance)
