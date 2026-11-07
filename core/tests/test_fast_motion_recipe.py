from cv.motion_analyzer import analyze_shot_motion
from cv.motion_fusion import fuse_motion
from recipe.ae_recipe import generate_ae_recipe
from schemas import Shot, TimeRange
from tests.test_motion_benchmark import benchmark


def test_half_second_round_trip_keeps_ae_position_peak(tmp_path):
    case = benchmark.generate_case(tmp_path, 'out_and_back', duration=0.5)
    measured = analyze_shot_motion(case['video_path'], 0, 0.5, 320, 180)
    assert measured.trajectory_status == 'complete'
    shot = Shot(shot_id='fast_pan', time=TimeRange(start=0, end=0.5, duration=0.5),
                measured_motion=measured, motion_summary=fuse_motion({}, measured))
    recipe = generate_ae_recipe(shot.model_dump())
    assert recipe['measured_motion']['sampling_target_fps'] == 16
    plan = recipe['animation_plan']
    assert plan['evidence_source'] == 'measured'
    points = next(curve['points'] for curve in plan['curves'] if curve['property'] == 'position_x')
    assert abs(points[0]['value']) < 0.5
    assert 18 < max(point['value'] for point in points[1:-1]) < 22
    assert abs(points[-1]['value']) < 0.5
