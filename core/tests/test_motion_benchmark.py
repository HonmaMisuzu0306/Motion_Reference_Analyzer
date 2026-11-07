"""Independent trajectory metrics must preserve errors, missing evidence and actual PTS."""
import importlib.util
import json
from pathlib import Path

import av
import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location(
    'benchmark_motion', Path(__file__).resolve().parents[2] / 'scripts/benchmark_motion.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def truth(timestamp, dx=0, dy=0, scale=1, rotation=0):
    return {'source_time': timestamp, 'matrix': benchmark.similarity_matrix(
        100, 100, dx, dy, scale, rotation).tolist(), 'rotation_deg': rotation}


def sample(timestamp, start=0, segment=0, dx=0, dy=0, scale=1, rotation=0):
    return {'source_time': timestamp, 'segment_start_time': start, 'segment_id': segment,
            'translation_x_px': dx, 'translation_y_px': dy,
            'scale_ratio': scale, 'rotation_deg': rotation}


def test_error_statistics_keep_sign_magnitude_and_empty_semantics():
    result = benchmark.summarize_errors([-3, 4])
    assert result == {'count': 2, 'mean_absolute': 3.5, 'rmse': pytest.approx((25 / 2) ** .5),
                      'max_absolute': 4, 'mean_signed': .5}
    assert benchmark.summarize_errors([])['rmse'] is None
    with pytest.raises(ValueError, match='finite'):
        benchmark.summarize_errors([float('nan')])


def test_metric_units_are_center_pixels_scale_percentage_points_and_degrees():
    frames = [truth(0), truth(1, dx=10, dy=20, scale=1.1, rotation=30)]
    values = [sample(0), sample(1, dx=13, dy=24, scale=1.12, rotation=32)]
    result = benchmark.evaluate_trajectory(frames, values, [0, 1], 100, 100)
    assert result['scored_nonreference_count'] == 1
    assert result['errors']['center_distance_px']['rmse'] == pytest.approx(5)
    assert result['errors']['scale_percentage_points']['rmse'] == pytest.approx(2)
    assert result['errors']['rotation_deg']['rmse'] == pytest.approx(2)


def test_bad_middle_point_is_scored_even_when_both_endpoints_are_exact():
    frames = [truth(0), truth(1, dx=30), truth(2)]
    result = benchmark.evaluate_trajectory(frames, [sample(0), sample(1), sample(2)],
                                           [0, 1, 2], 100, 100)
    assert result['errors']['center_distance_px']['mean_absolute'] == 15
    assert result['errors']['center_distance_px']['max_absolute'] == 30
    assert result['points'][-1]['errors']['center_distance_px'] == 0


def test_tracking_restart_uses_its_own_reference_without_bridging_missing_points():
    frames = [truth(t, dx=t * 10) for t in range(5)]
    values = [sample(0), sample(1, dx=10), sample(3, start=3, segment=1),
              sample(4, start=3, segment=1, dx=10)]
    result = benchmark.evaluate_trajectory(frames, values, list(range(5)), 100, 100)
    assert result['point_availability'] == .8
    assert result['missing_times'] == [2]
    assert result['segment_reference_count'] == 2
    assert result['scored_nonreference_count'] == 2
    assert result['errors']['center_distance_px']['rmse'] == 0


def test_relative_center_transform_is_matrix_composition_not_parameter_subtraction():
    # Reference center has already translated 10px; scaling around the original
    # center changes that translation as well. Relative center dx is 20-2*10=0.
    frames = [truth(1, dx=10), truth(2, dx=20, scale=2)]
    result = benchmark.evaluate_trajectory(frames, [sample(1, start=1), sample(2, start=1, scale=2)],
                                           [1, 2], 100, 100)
    assert result['points'][-1]['expected']['center_x_px'] == 0
    assert result['errors']['center_distance_px']['rmse'] == 0


def test_rotation_truth_is_unwrapped():
    frames = [truth(0, rotation=170), truth(1, rotation=380)]
    result = benchmark.evaluate_trajectory(frames, [sample(0), sample(1, rotation=210)],
                                           [0, 1], 100, 100)
    assert result['errors']['rotation_deg']['rmse'] == 0


def test_missing_all_predictions_is_unavailable_not_zero_error():
    result = benchmark.evaluate_trajectory([truth(0), truth(1, dx=10)], [], [0, 1], 100, 100)
    assert result['point_availability'] == 0
    assert result['missing_times'] == [0, 1]
    assert result['errors']['center_distance_px']['rmse'] is None
    empty = benchmark.evaluate_trajectory([], [], [], 100, 100)
    assert empty['point_availability'] is None


def test_prediction_off_actual_pts_is_unmatched_not_interpolated():
    result = benchmark.evaluate_trajectory([truth(0), truth(.16, dx=10)],
                                           [sample(0), sample(.15, dx=10)], [0, .16], 100, 100)
    assert result['point_availability'] == .5
    assert result['unmatched_measurement_times'] == [.15]
    assert result['scored_nonreference_count'] == 0


def test_partial_range_cannot_borrow_a_reference_outside_its_requested_samples():
    result = benchmark.evaluate_trajectory([truth(0), truth(1, dx=10), truth(2, dx=20)],
                                           [sample(1, dx=10), sample(2, dx=20)], [1, 2], 100, 100)
    assert result['point_availability'] == 0
    assert result['unmatched_measurement_times'] == [1, 2]
    assert result['errors']['center_distance_px']['rmse'] is None


def test_duplicate_predictions_and_invalid_times_are_rejected():
    with pytest.raises(ValueError, match='duplicates'):
        benchmark.evaluate_trajectory([truth(0), truth(1)], [sample(0), sample(0)], [0, 1], 100, 100)
    with pytest.raises(ValueError, match='finite'):
        benchmark.evaluate_trajectory([truth(float('nan'))], [], [], 100, 100)
    with pytest.raises(ValueError, match='actual decoded'):
        benchmark.evaluate_trajectory([truth(0), truth(1)], [], [0, .5], 100, 100)


def test_truth_center_rotation_has_no_invented_pan():
    matrix = benchmark.similarity_matrix(100, 60, scale=1.2, rotation_deg=45)
    assert matrix @ [50, 30, 1] == pytest.approx([50, 30, 1])
    assert matrix @ [60, 30, 1] == pytest.approx([50 + 12 / 2 ** .5, 30 + 12 / 2 ** .5, 1])


def test_encoded_vfr_has_actual_nonuniform_pts_nonzero_origin_and_known_final_pose(tmp_path):
    case = benchmark.generate_case(tmp_path, 'variable_pts', duration=1)
    with av.open(case['video_path']) as container:
        stream = container.streams.video[0]
        origin = stream.start_time * stream.time_base
        times = [float(frame.pts * frame.time_base - origin) for frame in container.decode(stream)]
    assert origin == pytest.approx(10)
    assert case['has_nonuniform_pts']
    assert [frame['source_time'] for frame in case['truth']] == times
    assert case['truth'][-1]['rotation_deg'] == 15
    center = np.array([case['width'] / 2, case['height'] / 2, 1])
    assert np.asarray(case['truth'][-1]['matrix']) @ center - center == pytest.approx([38.4, -21.6, 0])


def test_generation_rerun_keeps_identical_pixels_and_truth(tmp_path):
    def read_video(path):
        with av.open(path) as container:
            return [frame.to_ndarray(format='bgr24') for frame in container.decode(video=0)]

    first = benchmark.generate_case(tmp_path, 'horizontal_pan', duration=.5)
    pixels = read_video(first['video_path'])
    second = benchmark.generate_case(tmp_path, 'horizontal_pan', duration=.5)
    assert first['truth'] == second['truth']
    assert all(np.array_equal(a, b) for a, b in zip(pixels, read_video(second['video_path'])))


def test_real_encoded_gap_and_unobservable_case_keep_truth_and_missingness(tmp_path):
    report = benchmark.run_benchmark(tmp_path, cases=['occlusion_gap', 'low_texture'], duration=1)
    saved = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert saved['benchmark'] == report['benchmark']
    for case in report['cases']:
        assert case['truth'][-1]['matrix'][0][2] == pytest.approx(57.6)
        for measurement in case['measurements']:
            assert all(measurement['start_time'] <= t < measurement['end_time']
                       for t in measurement['expected_sample_times'])
            assert measurement['point_availability'] < 1
            assert not measurement['unmatched_measurement_times']
    low = report['cases'][1]['measurements'][0]
    assert low['point_availability'] == 0
    assert low['errors']['center_distance_px']['rmse'] is None
    gap = report['cases'][0]['measurements'][0]
    assert gap['segment_count'] == 2
    assert 0 < gap['tracked_duration_availability'] < 1


def test_dense_retry_scores_every_nonreference_sample(tmp_path):
    report = benchmark.run_benchmark(tmp_path, cases=['out_and_back'], duration=.5)
    full = report['cases'][0]['measurements'][0]
    assert report['settings']['analysis_target_fps'] == 8
    assert full['sampling_target_fps'] == 16
    assert full['total_pair_count'] == full['scored_nonreference_count'] == 7
    assert full['point_availability'] == 1
    assert full['unmatched_measurement_times'] == []
    assert full['errors']['center_distance_px']['max_absolute'] < 1
