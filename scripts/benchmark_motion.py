"""Evaluate motion trajectories on reproducible, actually encoded synthetic videos.

Run with the core environment: python scripts/benchmark_motion.py --output-dir work/motion-benchmark
Generated inputs and JSON are confined to the chosen directory. This is a controlled
geometric regression benchmark, not an estimate of accuracy on natural videos.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from bisect import bisect_left
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any

import av
import cv2
import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'core'
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

CASE_DESCRIPTIONS = {
    'horizontal_pan': 'Constant horizontal translation across a textured plane.',
    'vertical_pan': 'Constant upward translation across a textured plane.',
    'center_zoom': 'Uniform scale increase about the exact frame center.',
    'center_rotation': 'Clockwise rotation about the exact frame center in image coordinates.',
    'combined': 'Simultaneous center rotation, scale increase and translation.',
    'out_and_back': 'Sinusoidal horizontal excursion returning to the initial pose.',
    'alternating_shake': 'Repeated horizontal alternation with 24 half-cycles over the clip.',
    'low_texture': 'The same translating plane with constant pixels; motion is unobservable.',
    'occlusion_gap': 'Translating plane hidden by a full-frame opaque cover in the middle.',
    'variable_pts': 'Combined transform with nonuniform PTS and a nonzero source origin.',
}


def similarity_matrix(width: int, height: int, dx: float = 0, dy: float = 0,
                      scale: float = 1, rotation_deg: float = 0) -> np.ndarray:
    """Forward transform; positive rotation is clockwise for downward image y."""
    if width <= 0 or height <= 0 or scale <= 0:
        raise ValueError('Dimensions and scale must be positive')
    if not all(math.isfinite(v) for v in (dx, dy, scale, rotation_deg)):
        raise ValueError('Transform values must be finite')
    angle = math.radians(rotation_deg)
    linear = scale * np.array([[math.cos(angle), -math.sin(angle)],
                               [math.sin(angle), math.cos(angle)]])
    center = np.array([width / 2, height / 2])
    matrix = np.eye(3)
    matrix[:2, :2] = linear
    matrix[:2, 2] = center + [dx, dy] - linear @ center
    return matrix


def summarize_errors(values: list[float]) -> dict[str, float | int | None]:
    """No observations yield null errors, never a misleading perfect zero."""
    if any(not math.isfinite(value) for value in values):
        raise ValueError('Errors must be finite')
    if not values:
        return {'count': 0, 'mean_absolute': None, 'rmse': None, 'max_absolute': None,
                'mean_signed': None}
    data = np.asarray(values, dtype=np.float64)
    return {'count': len(values), 'mean_absolute': float(np.mean(np.abs(data))),
            'rmse': float(np.sqrt(np.mean(data ** 2))),
            'max_absolute': float(np.max(np.abs(data))), 'mean_signed': float(np.mean(data))}


def _strict_times(values: list[float], name: str) -> list[float]:
    values = [float(value) for value in values]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError(f'{name} must contain finite nonnegative times')
    if any(b <= a for a, b in pairwise(values)):
        raise ValueError(f'{name} must be strictly increasing, without duplicates')
    return values


def _index_at(times: list[float], value: float, tolerance: float = 1e-6) -> int | None:
    index = bisect_left(times, value)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(times)]
    if not candidates:
        return None
    closest = min(candidates, key=lambda i: abs(times[i] - value))
    return closest if abs(times[closest] - value) <= tolerance else None


def evaluate_trajectory(truth: list[dict[str, Any]], samples: list[dict[str, Any]],
                        expected_times: list[float], width: int, height: int) -> dict[str, Any]:
    """Compare every returned point with its exact decoded-frame truth and segment origin.

    No temporal interpolation or missing-point imputation is performed. Segment
    reference points are listed but excluded from error aggregates (identity there
    is guaranteed by construction). Availability includes them and is reported
    separately from accuracy. Scale error is percentage points, not relative %.
    """
    if min(width, height) <= 0:
        raise ValueError('Frame dimensions must be positive')
    truth_times = _strict_times([frame['source_time'] for frame in truth], 'Truth times')
    expected_times = _strict_times(expected_times, 'Expected sample times')
    sample_times = _strict_times([sample['source_time'] for sample in samples], 'Sample times')
    if any(_index_at(truth_times, t) is None for t in expected_times):
        raise ValueError('Expected sample times must be actual decoded frame times')
    center = np.array([width / 2, height / 2, 1.0])
    rows, unmatched, covered = [], [], set()
    for sample, timestamp in zip(samples, sample_times):
        frame_index = _index_at(truth_times, timestamp)
        reference_index = _index_at(truth_times, sample['segment_start_time'])
        expected_index = _index_at(expected_times, timestamp)
        reference_expected_index = _index_at(expected_times, sample['segment_start_time'])
        if None in (frame_index, reference_index, expected_index, reference_expected_index):
            unmatched.append(timestamp)
            continue
        if sample['segment_start_time'] > timestamp + 1e-6:
            raise ValueError('A segment reference cannot follow its sample')
        if expected_index in covered:
            raise ValueError('Multiple measurements cannot cover the same decoded frame')
        covered.add(expected_index)
        current, reference = truth[frame_index], truth[reference_index]
        relative = np.asarray(current['matrix']) @ np.linalg.inv(np.asarray(reference['matrix']))
        displacement = relative @ center - center
        expected_scale = float(math.hypot(relative[0, 0], relative[1, 0]))
        expected_rotation = current['rotation_deg'] - reference['rotation_deg']
        error_x = sample['translation_x_px'] - float(displacement[0])
        error_y = sample['translation_y_px'] - float(displacement[1])
        rows.append({
            'source_time': timestamp, 'segment_id': sample['segment_id'],
            'segment_start_time': sample['segment_start_time'],
            'is_reference': frame_index == reference_index,
            'visibility': current.get('visibility', 'visible'),
            'expected': {'center_x_px': float(displacement[0]), 'center_y_px': float(displacement[1]),
                         'scale_percent': 100 * (expected_scale - 1), 'rotation_deg': expected_rotation},
            'measured': {'center_x_px': sample['translation_x_px'], 'center_y_px': sample['translation_y_px'],
                         'scale_percent': 100 * (sample['scale_ratio'] - 1), 'rotation_deg': sample['rotation_deg']},
            'errors': {'center_distance_px': math.hypot(error_x, error_y),
                       'center_x_px': error_x, 'center_y_px': error_y,
                       'scale_percentage_points': 100 * (sample['scale_ratio'] - expected_scale),
                       'rotation_deg': sample['rotation_deg'] - expected_rotation},
        })
    scored = [row for row in rows if not row['is_reference']]
    metric_names = ('center_distance_px', 'center_x_px', 'center_y_px',
                    'scale_percentage_points', 'rotation_deg')
    return {
        'expected_sample_count': len(expected_times), 'returned_sample_count': len(samples),
        'aligned_sample_count': len(rows), 'scored_nonreference_count': len(scored),
        'segment_reference_count': len(rows) - len(scored),
        'point_availability': len(covered) / len(expected_times) if expected_times else None,
        'missing_times': [t for i, t in enumerate(expected_times) if i not in covered],
        'unmatched_measurement_times': unmatched,
        'errors': {name: summarize_errors([row['errors'][name] for row in scored]) for name in metric_names},
        'points': rows,
    }


def _texture(width: int, height: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Large and small nonperiodic details remain trackable after actual compression.
    image = np.zeros((height, width, 3), dtype=np.float32)
    for cell, weight in ((5, .25), (17, .45), (43, .30)):
        noise = rng.integers(10, 246, (height // cell + 2, width // cell + 2, 3), dtype=np.uint8)
        image += cv2.resize(noise, (width, height), interpolation=cv2.INTER_LINEAR) * weight
    return np.clip(image, 0, 255).astype(np.uint8)


def _pose(name: str, progress: float, width: int, height: int) -> tuple[float, float, float, float]:
    if name in ('horizontal_pan', 'low_texture', 'occlusion_gap'):
        return .18 * width * progress, 0, 1, 0
    if name == 'vertical_pan':
        return 0, -.18 * height * progress, 1, 0
    if name == 'center_zoom':
        return 0, 0, 1 + .25 * progress, 0
    if name == 'center_rotation':
        return 0, 0, 1, 20 * progress
    if name == 'out_and_back':
        return .20 * width * math.sin(math.pi * progress), 0, 1, 0
    if name == 'alternating_shake':
        return .015 * width * (1 if int(progress * 24) % 2 else -1), 0, 1, 0
    return .12 * width * progress, -.12 * height * progress, 1 + .2 * progress, 15 * progress


def generate_case(output_dir: Path, name: str, *, width: int = 320, height: int = 180,
                  fps: int = 24, duration: float = 3, seed: int = 903) -> dict[str, Any]:
    """Render known matrices, encode H.264, then attach truth to decoded PTS by frame order."""
    if name not in CASE_DESCRIPTIONS:
        raise ValueError(f'Unknown case: {name}')
    if min(width, height) < 32 or width % 2 or height % 2:
        raise ValueError('Use even dimensions of at least 32 pixels')
    if fps <= 0 or not math.isfinite(duration) or duration < .5:
        raise ValueError('Use positive FPS and at least 0.5 seconds')
    variable = name == 'variable_pts'
    frame_times = []
    if variable:
        ticks, index = 0, 0
        while ticks / 24000 < duration:
            frame_times.append(ticks / 24000)
            ticks += (768, 1200, 984, 1560)[index % 4]
            index += 1
    else:
        frame_times = [i / fps for i in range(round(fps * duration))]
    if len(frame_times) < 3:
        raise ValueError('At least three encoded frames are required')
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f'{name}.mp4'
    # Overscan prevents black borders from becoming spurious stationary features.
    canvas = _texture(width * 2, height * 2, seed)
    canvas_to_initial = np.array([[1., 0, -width / 2], [0, 1., -height / 2], [0, 0, 1.]])
    truth = []
    start = time.perf_counter()
    origin = 10 if variable else 0
    with av.open(str(path), 'w') as container:
        stream = container.add_stream('libx264', rate=fps)
        stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
        stream.time_base = Fraction(1, 24000)
        stream.codec_context.time_base = Fraction(1, 24000)
        stream.codec_context.max_b_frames = 0
        stream.options = {'crf': '18', 'preset': 'fast', 'threads': '1'}
        for timestamp in frame_times:
            progress = timestamp / frame_times[-1]
            dx, dy, scale, rotation = _pose(name, progress, width, height)
            matrix = similarity_matrix(width, height, dx, dy, scale, rotation)
            image = cv2.warpAffine(canvas, (matrix @ canvas_to_initial)[:2], (width, height),
                                   flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            visibility = 'visible'
            if name == 'low_texture' or (name == 'occlusion_gap' and .36 <= progress < .60):
                image.fill(128)
                visibility = 'unobservable' if name == 'low_texture' else 'occluded'
            frame = av.VideoFrame.from_ndarray(image, format='bgr24')
            frame.pts = round((origin + timestamp) * 24000)
            frame.time_base = Fraction(1, 24000)
            for packet in stream.encode(frame):
                container.mux(packet)
            truth.append({'source_time': timestamp, 'render_time': timestamp,
                          'matrix': matrix.tolist(), 'rotation_deg': rotation, 'visibility': visibility})
        for packet in stream.encode():
            container.mux(packet)
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        raw_origin = stream.start_time * stream.time_base if stream.start_time is not None else 0
        actual_origin = float(raw_origin)
        decoded = [float(frame.pts * frame.time_base - raw_origin) for frame in container.decode(stream)]
    _strict_times(decoded, 'Decoded timestamps')
    if len(decoded) != len(truth):
        raise RuntimeError('Encoder changed frame count; rendered truth cannot be aligned')
    for row, timestamp in zip(truth, decoded):
        row['source_time'] = timestamp
    return {'name': name, 'description': CASE_DESCRIPTIONS[name], 'video_path': str(path.resolve()),
            'width': width, 'height': height, 'frame_count': len(truth), 'nominal_fps': fps,
            'source_origin_seconds': actual_origin, 'end_time': decoded[-1] + 1 / fps,
            'has_nonuniform_pts': len({round(b - a, 8) for a, b in pairwise(decoded)}) > 1,
            'seed': seed, 'generation_seconds': time.perf_counter() - start, 'truth': truth}


def _truth_excursion(truth: list[dict[str, Any]], times: list[float], width: int, height: int) -> dict[str, float | None]:
    if not times:
        return {'max_center_excursion_px': None, 'final_center_displacement_px': None}
    lookup = {round(row['source_time'], 6): row for row in truth}
    first = np.asarray(lookup[round(times[0], 6)]['matrix'])
    center = np.array([width / 2, height / 2, 1.0])
    magnitudes = [float(np.linalg.norm((np.asarray(lookup[round(t, 6)]['matrix']) @ np.linalg.inv(first) @ center - center)[:2])) for t in times]
    return {'max_center_excursion_px': max(magnitudes), 'final_center_displacement_px': magnitudes[-1]}


def run_benchmark(output_dir: Path, *, cases: list[str] | None = None, width: int = 320,
                  height: int = 180, fps: int = 24, duration: float = 3,
                  target_fps: float = 8) -> dict[str, Any]:
    from cv.cache import CV_ALGORITHM_VERSION
    from cv.frame_sampler import iter_frames_for_cv
    from cv.motion_analyzer import analyze_shot_motion

    output_dir = Path(output_dir).resolve()
    if not math.isfinite(target_fps) or target_fps <= 0:
        raise ValueError('Analysis FPS must be finite and positive')
    results = []
    for name in cases if cases is not None else CASE_DESCRIPTIONS:
        case = generate_case(output_dir, name, width=width, height=height, fps=fps, duration=duration)
        measurements = []
        for label, start, end in [('full', 0., case['end_time']),
                                  ('partial', .21 * case['end_time'], .77 * case['end_time'])]:
            started = time.perf_counter()
            motion = analyze_shot_motion(case['video_path'], start, end, width, height,
                                         target_fps=target_fps)
            elapsed = time.perf_counter() - started
            retained_fps = motion.sampling_target_fps or target_fps
            expected_times = [frame['timestamp'] for frame in iter_frames_for_cv(
                case['video_path'], start, end, target_fps=retained_fps)]
            data = motion.model_dump()
            evaluation = evaluate_trajectory(case['truth'], data['trajectory'], expected_times, width, height)
            valid_duration = sum(pair['end_time'] - pair['start_time'] for pair in data['pairs'] if pair['valid'])
            sampled_span = expected_times[-1] - expected_times[0] if len(expected_times) > 1 else 0
            measurements.append({
                'range': label, 'start_time': start, 'end_time': end,
                'half_open': True, 'expected_sample_times': expected_times,
                'sampling_target_fps': retained_fps,
                'status': motion.status, 'trajectory_status': motion.trajectory_status,
                'method': motion.method, 'stability': motion.stability, 'shake_score': motion.shake_score,
                'translation_reference': motion.translation_reference,
                'elapsed_seconds': elapsed, 'confidence': motion.confidence,
                'valid_pair_count': motion.valid_pair_count, 'total_pair_count': motion.total_pair_count,
                'valid_pair_availability': motion.valid_pair_count / motion.total_pair_count if motion.total_pair_count else None,
                'tracked_duration_availability': valid_duration / sampled_span if sampled_span else None,
                'segment_count': len({row['segment_id'] for row in data['trajectory']}),
                'invalid_pair_times': [[pair['start_time'], pair['end_time']] for pair in data['pairs'] if not pair['valid']],
                'truth_excursion': _truth_excursion(case['truth'], expected_times, width, height),
                **evaluation,
            })
        case['measurements'] = measurements
        results.append(case)
    report = {
        'benchmark': 'encoded-motion-trajectory-v1',
        'cv_algorithm_version': CV_ALGORITHM_VERSION,
        'scope': 'Synthetic planar similarity transforms only; not natural-video accuracy.',
        'semantics': {
            'coordinates': 'Original pixels, frame center=(width/2,height/2); positive y down and rotation clockwise.',
            'truth': 'Known forward render matrices mapped to actual decoded PTS, relative to each measured segment start.',
            'accuracy': 'Every aligned nonreference trajectory point; no interpolation or endpoint-only averaging.',
            'scale_error': 'Percentage-point difference of scale change; 1.10 versus 1.12 means 2 points.',
            'missing': 'Missing measurements reduce availability; empty accuracy aggregates are null, not zero.',
            'occlusion': 'Underlying motion truth remains intact while hidden/unobservable; no assumed zero motion.',
            'timing': 'Elapsed analysis includes decode and CV, excludes generation and independent sample inventory.',
        },
        'settings': {'width': width, 'height': height, 'fps': fps, 'duration': duration,
                     'analysis_target_fps': target_fps, 'codec': 'libx264', 'crf': 18, 'seed': 903},
        'runtime_versions': {'python': sys.version.split()[0], 'pyav': av.__version__,
                             'opencv': cv2.__version__, 'numpy': np.__version__},
        'cases': results,
        'total_analysis_seconds': sum(m['elapsed_seconds'] for case in results for m in case['measurements']),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('work/motion-benchmark'))
    parser.add_argument('--cases', nargs='+', choices=CASE_DESCRIPTIONS)
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--height', type=int, default=180)
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--duration', type=float, default=3)
    parser.add_argument('--target-fps', type=float, default=8)
    args = parser.parse_args()
    report = run_benchmark(args.output_dir, cases=args.cases, width=args.width, height=args.height,
                           fps=args.fps, duration=args.duration, target_fps=args.target_fps)
    print(json.dumps({'report': str((args.output_dir / 'report.json').resolve()),
                      'total_analysis_seconds': report['total_analysis_seconds'],
                      'cases': [{'name': case['name'], 'measurements': [
                          {**{key: result[key] for key in ('range', 'status', 'stability', 'shake_score', 'point_availability',
                                                          'tracked_duration_availability', 'elapsed_seconds')},
                           'rmse': {key: result['errors'][key]['rmse'] for key in (
                               'center_distance_px', 'scale_percentage_points', 'rotation_deg')}}
                          for result in case['measurements']]} for case in report['cases']]},
                     indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
