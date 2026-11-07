"""Benchmark metrics must not inflate success or require hand-supplied sample files."""
import importlib.util
import json
from pathlib import Path

import av
import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location(
    'benchmark_scenes', Path(__file__).resolve().parents[2] / 'scripts/benchmark_scenes.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_one_prediction_never_matches_multiple_cuts():
    result = benchmark.match_cuts([1, 1.08], [1.04], .05)
    assert (result['true_positives'], result['false_negatives']) == (1, 1)
    assert result['precision'] == 1 and result['recall'] == .5


def test_duplicate_predictions_remain_false_positives():
    result = benchmark.match_cuts([1], [1, 1], 0)
    assert result['true_positives'] == 1 and result['false_positives'] == 1
    assert result['precision'] == .5


def test_matching_maximizes_count_before_minimizing_error():
    # Nearest-first would consume 1.01 for 1.0 and miss the second ground-truth event.
    result = benchmark.match_cuts([1, 1.1], [.91, 1.01], .1)
    assert result['true_positives'] == 2 and result['f1'] == 1
    nearest = benchmark.match_cuts([1, 1.1], [1.08], .1)
    assert nearest['matches'][0]['expected_time'] == 1.1


def test_tolerance_boundary_is_inclusive_and_inputs_are_sorted():
    result = benchmark.match_cuts([2, 1], [2.05, .95], .05)
    assert result['true_positives'] == 2
    assert benchmark.match_cuts([1], [1.0501], .05)['true_positives'] == 0


@pytest.mark.parametrize('expected,detected,p,r,f1', [
    ([], [], 1, 1, 1), ([], [1], 0, 1, 0), ([1], [], 0, 0, 0),
])
def test_empty_metrics_are_explicit(expected, detected, p, r, f1):
    result = benchmark.match_cuts(expected, detected, .05)
    assert (result['precision'], result['recall'], result['f1']) == (p, r, f1)
    assert result['mean_absolute_error_seconds'] is None


@pytest.mark.parametrize('expected,detected,tolerance', [
    ([float('nan')], [], .05), ([], [float('inf')], .05), ([-1], [], .05),
    ([], [], -.1), ([], [], float('nan')),
])
def test_invalid_metrics_input_is_rejected(expected, detected, tolerance):
    with pytest.raises(ValueError):
        benchmark.match_cuts(expected, detected, tolerance)


def test_encoded_hard_cut_and_static_negative_case(tmp_path):
    report = benchmark.run_benchmark(tmp_path, cases=['same_color_layout_cut', 'static_noise'])
    loaded = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert loaded == report
    assert report['cases'][0]['expected_cuts'] == [1.5]
    for case in report['cases']:
        assert (tmp_path / case['video']).is_file()
        for mode in ('full_video', 'selected_range'):
            assert case[mode]['f1'] == 1
            assert case[mode]['elapsed_seconds'] >= 0


def test_generator_pixels_are_reproducible_for_same_seed(tmp_path):
    videos = [benchmark.generate_case(tmp_path / label, 'static_noise', duration=.5)['video']
              for label in ('first', 'second')]
    decoded = []
    for label, name in zip(('first', 'second'), videos):
        with av.open(str(tmp_path / label / name)) as container:
            decoded.append([frame.to_ndarray(format='bgr24') for frame in container.decode(video=0)])
    assert len(decoded[0]) == len(decoded[1]) == 12
    assert all(np.array_equal(a, b) for a, b in zip(*decoded))


def test_invalid_case_does_not_write_output(tmp_path):
    target = tmp_path / 'not-created'
    with pytest.raises(ValueError):
        benchmark.run_benchmark(target, cases=['not-a-case'])
    assert not target.exists()


def test_encoded_short_insert_and_flash_at_real_cut(tmp_path):
    report = benchmark.run_benchmark(tmp_path, cases=['cross_content_cut', 'two_frame_insert', 'flash_at_cut'])
    assert [case['expected_cuts'] for case in report['cases']] == [[1.5], [1.5, 38 / 24], [1.5]]
    for case in report['cases']:
        for mode in ('full_video', 'selected_range'):
            assert case[mode]['f1'] == 1
