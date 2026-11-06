from math import cos, radians, sin

import pytest

from recipe.ae_recipe import generate_ae_recipe
from schemas.measured_motion import MeasuredMotion, MotionSample


def shot_with_middle_pose(*, dx=0, dy=0, scale=1, angle=0, width=320, height=180):
    trajectory = []
    for time, x, y, zoom, rotation in [(4, 0, 0, 1, 0), (4.25, dx, dy, scale, angle), (4.5, 0, 0, 1, 0)]:
        a = zoom * cos(radians(rotation))
        b = zoom * sin(radians(rotation))
        cx, cy = width / 2, height / 2
        matrix = ((a, -b, x + cx - a * cx + b * cy),
                  (b, a, y + cy - b * cx - a * cy))
        trajectory.append(MotionSample(
            source_time=time, segment_id=0, segment_start_time=4, matrix=matrix,
            translation_x_px=x, translation_y_px=y, translation_x_ratio=x/width,
            translation_y_ratio=y/height, scale_ratio=zoom, rotation_deg=rotation,
        ))
    measured = MeasuredMotion(confidence=.95, trajectory_status='complete', trajectory=trajectory,
                              translation_reference='frame_center', sample_count=3, total_pair_count=2,
                              valid_pair_count=2, frame_width=width, frame_height=height)
    return {'time': {'start': 4, 'end': 4.6}, 'measured_motion': measured.model_dump()}


@pytest.mark.parametrize(('pose', 'margins'), [
    ({'dx': 63}, (63, 0, 0, 0)),
    ({'dx': -12.25, 'dy': -7}, (0, 13, 0, 7)),
    ({'scale': .5}, (160, 160, 90, 90)),
    ({'scale': 1.5}, (0, 0, 0, 0)),
    ({'angle': 90}, (24, 24, 94, 94)),
    ({'angle': 45}, (24, 24, 87, 87)),
    # AE leaves vertical Position untouched below its measured channel threshold.
    ({'dx': 63, 'dy': .7}, (63, 0, 0, 0)),
    ({}, (0, 0, 0, 0)),
])
def test_padding_covers_linear_ae_motion_in_original_pixels(pose, margins):
    plan = generate_ae_recipe(shot_with_middle_pose(**pose))['animation_plan']
    left, right, top, bottom = margins
    assert plan['artwork_padding'] == {'left_px': left, 'right_px': right, 'top_px': top, 'bottom_px': bottom,
                                      'width_px': 320 + left + right, 'height_px': 180 + top + bottom}
    assert any('采样之间' in note and '留边' in note for note in plan['notes'])


@pytest.mark.parametrize('case', ['partial', 'outside', 'low_confidence', 'semantic', 'too_large'])
def test_no_artwork_size_for_unusable_evidence_or_oversize_art(case):
    shot = shot_with_middle_pose(dx=30000 if case == 'too_large' else 63)
    if case == 'outside':
        shot['time']['end'] = 4.5
    elif case == 'partial':
        shot['measured_motion']['trajectory_status'] = 'partial'
    elif case == 'low_confidence':
        shot['measured_motion']['confidence'] = .1
    elif case == 'semantic':
        del shot['measured_motion']
        shot['motion'] = {'type': 'pan_left', 'strength': 1, 'confidence': .8}
    assert 'artwork_padding' not in generate_ae_recipe(shot)['animation_plan']


def test_coupled_motion_bound_matches_dense_independent_affine_inverse():
    import numpy as np

    plan = generate_ae_recipe(shot_with_middle_pose(angle=90, scale=.5, dx=20, dy=-10))['animation_plan']
    padding = plan['artwork_padding']
    required = np.zeros(4)
    corners = np.array([[0, 0], [320, 0], [320, 180], [0, 180]])
    center = np.array([160, 90])
    for fraction in np.linspace(0, 1, 2001):
        angle = radians(90 * fraction)
        matrix = (1 - .5 * fraction) * np.array([[cos(angle), -sin(angle)], [sin(angle), cos(angle)]])
        local = (corners - center - [20 * fraction, -10 * fraction]) @ np.linalg.inv(matrix).T + center
        required = np.maximum(required, [-local[:, 0].min(), local[:, 0].max() - 320,
                                         -local[:, 1].min(), local[:, 1].max() - 180])
    actual = np.array([padding[f'{side}_px'] for side in ('left', 'right', 'top', 'bottom')])
    assert np.all(actual >= required - 1e-9)
    assert np.all(actual <= required + 1.051)


def test_no_continuous_padding_claim_when_refinement_budget_is_exhausted(monkeypatch):
    from recipe import artwork

    monkeypatch.setattr(artwork, 'MAX_EXTRA_SPLITS', 0)
    plan = generate_ae_recipe(shot_with_middle_pose(angle=90, scale=.5, dx=20, dy=-10))['animation_plan']
    assert plan['curves']
    assert 'artwork_padding' not in plan


@pytest.mark.parametrize('angle', [-1080, 1_000_000])
def test_multiple_turns_stay_bounded_by_half_diagonal(angle):
    plan = generate_ae_recipe(shot_with_middle_pose(angle=angle))['animation_plan']
    assert plan['artwork_padding'] == dict(left_px=24, right_px=24, top_px=94, bottom_px=94,
                                          width_px=368, height_px=368)


def test_one_frame_and_unresolvable_extreme_angles_have_no_continuous_claim():
    from types import SimpleNamespace

    from recipe.artwork import artwork_padding

    sample = [SimpleNamespace(source_time=0)]
    assert artwork_padding([], 0, [], 320, 180) is None
    assert artwork_padding(sample, 0, [], 320, 180) is None
    assert artwork_padding(sample + sample, 0, [], 320, 180) is None
    curve = {'property': 'rotation', 'points': [{'time': 0, 'value': 0}, {'time': 1, 'value': 1e300}]}
    assert artwork_padding(sample + [SimpleNamespace(source_time=1)], 0, [curve], 320, 180) is None
