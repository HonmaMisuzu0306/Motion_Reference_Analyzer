"""AE suggestions must distinguish measurements from trial values and retain units."""
import json

import pytest

from recipe.ae_recipe import generate_ae_recipe
from schemas import Shot, TimeRange
from schemas.measured_motion import MeasuredMotion


def shot_with_motion(**measured):
    return Shot(
        shot_id='shot_001', time=TimeRange(start=12, end=14, duration=2),
        motion={'type': 'push_in', 'strength': .7, 'confidence': .9},
        measured_motion=MeasuredMotion(confidence=.85, valid_pair_count=7, total_pair_count=7,
                                       sample_count=8, **measured),
    ).model_dump()


def test_measured_plan_preserves_units_source_times_and_signed_offsets():
    recipe = generate_ae_recipe(shot_with_motion(
        scale_change_percent=8, translation_x_ratio=.05, translation_y_ratio=-.025, rotation_deg=-2))
    plan = recipe['animation_plan']
    assert plan['evidence_source'] == 'measured'
    assert (plan['source_start'], plan['source_end'], plan['duration']) == (12, 14, 2)
    keys = {item['property']: item for item in plan['keyframes']}
    assert keys['global_scale']['to'] == 108
    assert keys['position_x']['to'] == 5
    assert keys['position_x']['unit'] == '画面宽度（%）'
    assert keys['position_y']['to'] == -2.5
    assert keys['position_y']['unit'] == '画面高度（%）'
    assert keys['rotation']['to'] == -2
    assert keys['rotation']['unit'] == '角度（°）'
    assert all((item['start_time'], item['end_time']) == (0, 2) for item in keys.values())
    assert any('线性' in note and '贝塞尔参数' in note for note in plan['notes'])
    json.dumps(recipe, allow_nan=False)


def test_reliable_static_evidence_does_not_invent_semantic_push_in():
    shot = shot_with_motion()
    shot['motion_summary'] = {'conflict': True}
    recipe = generate_ae_recipe(shot)
    assert recipe['transform'] == {}
    assert recipe['animation_plan']['keyframes'] == []
    assert recipe['animation_plan']['evidence_source'] == 'measured'
    assert any('保持静止' in note for note in recipe['animation_plan']['notes'])
    assert any('分歧' in note for note in recipe['animation_plan']['notes'])


@pytest.mark.parametrize('override', [
    {'status': 'failed'}, {'confidence': .2}, {'valid_pair_count': 0},
    {'scale_change_percent': float('nan')},
])
def test_unreliable_measurement_uses_only_explicit_semantic_trial(override):
    shot = shot_with_motion(translation_x_ratio=.5)
    shot['measured_motion'].update(override)
    recipe = generate_ae_recipe(shot)
    assert 'position_x' not in recipe['transform']
    trial = recipe['transform']['character_scale']
    assert trial['to'] == 114 and trial['unit'] == '缩放（%）'
    assert trial['basis'] == 'AI 方向判断的试作值'
    assert recipe['animation_plan']['evidence_source'] == 'semantic'
    json.dumps(recipe, allow_nan=False)


def test_unreliable_semantic_and_measured_data_do_not_generate_numbers():
    shot = shot_with_motion(status='failed')
    shot['motion']['confidence'] = .2
    recipe = generate_ae_recipe(shot)
    assert recipe['transform'] == {}
    assert recipe['animation_plan']['keyframes'] == []
    assert recipe['animation_plan']['evidence_source'] == 'insufficient'


def test_semantic_pan_retains_legacy_pixel_units_explicitly():
    shot = shot_with_motion(status='failed')
    shot['motion'] = {'type': 'pan_left', 'strength': .5, 'confidence': .8}
    recipe = generate_ae_recipe(shot)
    assert recipe['transform']['position_x']['to'] == -100
    assert recipe['transform']['position_x']['unit'] == '像素'


@pytest.mark.parametrize('time', [{}, {'start': 2, 'end': 2}, {'start': 3, 'end': 1}])
def test_missing_or_invalid_timing_never_invents_keyframe_times(time):
    shot = shot_with_motion(scale_change_percent=5)
    shot['time'] = time
    plan = generate_ae_recipe(shot)['animation_plan']
    assert plan['duration'] is None and plan['keyframes'] == []
    json.dumps(plan, allow_nan=False)


@pytest.mark.parametrize('override', [
    {'translation_x_ratio': 1e308}, {'translation_y_ratio': -1e308},
    {'scale_change_percent': -101}, {'confidence': 1.1},
    {'trajectory_status': 'unrecognized'}, {'trajectory': [{'source_time': 12}]},
])
def test_invalid_legacy_measurements_cannot_be_published_as_ae_parameters(override):
    shot = shot_with_motion(translation_x_ratio=.5)
    shot['measured_motion'].update(override)
    recipe = generate_ae_recipe(shot)
    assert recipe['animation_plan']['evidence_source'] == 'semantic'
    assert 'position_x' not in recipe['transform']
    json.dumps(recipe, allow_nan=False)


def test_nested_nonfinite_values_in_legacy_tuples_are_safe_json():
    shot = shot_with_motion()
    shot['ae_hypothesis']['notes'] = ('legacy', {'values': (float('nan'), float('inf'))})
    recipe = generate_ae_recipe(shot)
    assert recipe['hypothesis']['notes'] == ['legacy', {'values': [None, None]}]
    json.dumps(recipe, allow_nan=False)


def test_nullable_legacy_sections_and_invalid_effect_confidences_do_not_crash_recipe():
    shot = shot_with_motion()
    for key in ('observations', 'motion', 'measured_motion', 'typography', 'typography_tracks',
                'ae_hypothesis', 'rhythm', 'motion_summary'):
        shot[key] = None
    shot['visual_effects'] = [None, {'type': 'glow', 'confidence': None},
                              {'type': 'noise', 'confidence': 'invalid'}]
    recipe = generate_ae_recipe(shot)
    assert recipe['animation_plan']['evidence_source'] == 'insufficient'
    assert recipe['effects'] == []
    json.dumps(recipe, allow_nan=False)


def test_unknown_typography_geometry_does_not_claim_center_or_nan_size():
    shot = shot_with_motion()
    shot['typography_tracks'] = [{'average_bbox': {'height': float('nan')}}, {'average_bbox': None},
                                 {'average_bbox': {'x': 0, 'y': 0, 'width': 1, 'height': 1e308}}]
    typography = generate_ae_recipe(shot)['typography']
    assert all(track['position'] == track['estimated_size'] == 'unknown' for track in typography)
    json.dumps(typography, allow_nan=False)

def test_same_subtitle_in_two_intervals_keeps_its_own_motion_advice():
    from ocr.tracking import build_text_tracks
    from tests.test_ocr import _make_region

    regions = [(0, .3), (.25, .3), (2, .3), (2.25, .48)]
    tracks = build_text_tracks([
        {'timestamp': t, 'regions': [_make_region('AGAIN', x, .4, .2, .1)]} for t, x in regions
    ])
    result = generate_ae_recipe({'typography_tracks': [track.model_dump() for track in tracks]})
    stationary, sliding = result['typography']
    assert stationary['text'] == sliding['text'] == 'again'
    assert stationary['track_id'] == tracks[0].track_id != sliding['track_id'] == tracks[1].track_id
    assert set(stationary['suggested_animation']) == {'hold'}
    assert set(sliding['suggested_animation']) == {'position'}
    assert '向右' in sliding['suggested_animation']['position']
    assert result['layers'] == [{'role': 'typography', 'suggestion': '独立文字图层'}]


def test_single_ocr_sample_and_vision_only_text_do_not_generate_temporal_animation():
    for shot in ({'typography_tracks': [{'frame_count': 1, 'movement': 'slide_right', 'appearance': 'fade'}]},
                 {'typography': {'has_text': True}}):
        assert set(generate_ae_recipe(shot)['typography'][0]['suggested_animation']) == {'hold'}

@pytest.mark.parametrize(('kind', 'offset'), [('tilt_up', -100), ('tilt_down', 100)])
def test_semantic_vertical_pan_offers_pixel_trial_only(kind, offset):
    shot = shot_with_motion(status='failed')
    shot['motion'] = {'type': kind, 'strength': .5, 'confidence': .8}
    plan = generate_ae_recipe(shot)['animation_plan']
    assert plan['evidence_source'] == 'semantic'
    key, = plan['keyframes']
    assert (key['property'], key['unit'], key['from'], key['to']) == ('position_y', '像素', 0, offset)
    assert not plan['curves']
    assert any('起始 Position Y' in note for note in plan['notes'])


@pytest.mark.parametrize('status,trajectory_status', [
    ('localized_support','partial'), ('mixed_support','partial'),
    ('incomplete_tracking','partial'), ('ok','partial'), ('failed','not_measured'),
])
def test_unavailable_camera_totals_are_not_exported_as_static(status, trajectory_status):
    shot = shot_with_motion()
    shot['measured_motion'].update(status=status, trajectory_status=trajectory_status)
    shot['motion'] = {}
    recipe = generate_ae_recipe(shot)
    assert recipe['camera']['type'] == 'unknown'
    assert recipe['animation_plan']['evidence_source'] == 'insufficient'
    assert not {'scale_change_percent', 'translation_x_ratio', 'translation_y_ratio', 'rotation_deg',
                'motion_strength'} & recipe['measured_motion'].keys()
    assert recipe['measured_motion']['valid_pair_count'] == 7
