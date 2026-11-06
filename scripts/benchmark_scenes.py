"""Reproducible hard-cut evaluation on encoded synthetic media, without user data.

Run from the repository root:
    python scripts/benchmark_scenes.py --output-dir work/scene-benchmark

The output directory is required. It contains generated MP4s and report.json only;
no project, model, cache or reference-library service is started.
"""
from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import cv2
import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'core'
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

CASE_DESCRIPTIONS = {
    'same_color_layout_cut': 'Equal global colors, reversed left/right composition at the hard cut.',
    'brightness_cut': 'A sustained hard cut between dark and bright rendered frames.',
    'static_noise': 'One still scene with independent low-amplitude sensor/compression-like noise.',
    'slow_pan': 'Continuous horizontal camera motion, one source pixel per decoded frame.',
    'fast_pan': 'Continuous horizontal camera motion, eight source pixels per decoded frame.',
    'single_frame_flash': 'One bright flash frame followed by the identical original scene; no edit.',
    'exposure_ramp': 'A smooth exposure change within one scene; no hard cut.',
    'dissolve': 'A gradual cross-dissolve; deliberately no hard-cut event is annotated.',
    'cross_content_cut': 'A sustained cut between unrelated deterministic textured scenes.',
    'two_frame_insert': 'A two-frame bright insert, with separate entry and exit hard cuts.',
    'flash_at_cut': 'A flash coinciding with an actual scene change; first observable change is the boundary.',
}


def _times(values: list[float], name: str) -> list[float]:
    result = [float(value) for value in values]
    if any(not math.isfinite(value) or value < 0 for value in result):
        raise ValueError(f'{name} must contain finite, nonnegative seconds')
    return sorted(result)


def _metrics(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    # No-event/no-prediction is a correct negative case. False positives still give F1=0.
    precision = tp / (tp + fp) if tp + fp else float(fn == 0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
            'precision': precision, 'recall': recall, 'f1': f1}


def match_cuts(expected: list[float], detected: list[float], tolerance: float) -> dict[str, Any]:
    """Maximum one-to-one matches within inclusive tolerance, then minimum total error.

    Duplicate predictions remain predictions, and cannot match an event twice. A
    chronological dynamic program avoids nearest-neighbor greedy undercounting.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('tolerance must be finite and nonnegative')
    truth, predictions = _times(expected, 'expected'), _times(detected, 'detected')
    rows, cols = len(truth), len(predictions)
    counts = [[0] * (cols + 1) for _ in range(rows + 1)]
    errors = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    actions = [[''] * cols for _ in range(rows)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            choices = [(counts[i + 1][j], errors[i + 1][j], 0, 'miss'),
                       (counts[i][j + 1], errors[i][j + 1], 1, 'false_positive')]
            delta = abs(predictions[j] - truth[i])
            if delta <= tolerance or math.isclose(delta, tolerance, rel_tol=0, abs_tol=1e-12):
                choices.append((1 + counts[i + 1][j + 1], delta + errors[i + 1][j + 1], 2, 'match'))
            count, error, _, action = max(choices, key=lambda choice: (choice[0], -choice[1], choice[2]))
            counts[i][j], errors[i][j], actions[i][j] = count, error, action
    pairs, missed, extra = [], [], []
    i = j = 0
    while i < rows and j < cols:
        action = actions[i][j]
        if action == 'match':
            pairs.append({'expected_time': truth[i], 'detected_time': predictions[j],
                          'error_seconds': predictions[j] - truth[i]})
            i, j = i + 1, j + 1
        elif action == 'miss':
            missed.append(truth[i])
            i += 1
        else:
            extra.append(predictions[j])
            j += 1
    missed.extend(truth[i:])
    extra.extend(predictions[j:])
    return {'expected_count': rows, 'detected_count': cols,
            **_metrics(len(pairs), len(extra), len(missed)),
            'matches': pairs, 'missed_cuts': missed, 'extra_cuts': extra,
            'mean_absolute_error_seconds': (
                sum(abs(pair['error_seconds']) for pair in pairs) / len(pairs) if pairs else None)}


def _texture(width: int, height: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    small = rng.integers(20, 236, (height // 16 + 1, width // 16 + 1, 3), dtype=np.uint8)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)


def generate_case(output_dir: Path, name: str, *, fps: int = 24, duration: float = 3,
                  width: int = 192, height: int = 128, seed: int = 173) -> dict[str, Any]:
    """Create deterministic pixels and encode them; cut times derive from frame PTS."""
    if name not in CASE_DESCRIPTIONS:
        raise ValueError(f'Unknown case: {name}')
    if fps <= 0 or not math.isfinite(duration) or duration <= 0 or width < 16 or height < 16:
        raise ValueError('Use positive FPS/duration and dimensions of at least 16 pixels')
    if width % 2 or height % 2:
        raise ValueError('yuv420p requires even width and height')
    count = round(fps * duration)
    if count < 8:
        raise ValueError('At least eight frames are required for benchmark cases')
    duration = count / fps
    cut_frame = count // 2
    frame_time = cut_frame / fps
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f'{name}.mp4'
    rng = np.random.default_rng(seed)
    base = _texture(width, height, seed)
    other = _texture(width, height, seed + 1)
    world = _texture(width + count * 8, height, seed)
    expected = [frame_time] if name in {
        'same_color_layout_cut', 'brightness_cut', 'cross_content_cut', 'flash_at_cut'} else []
    if name == 'two_frame_insert':
        expected = [frame_time, (cut_frame + 2) / fps]
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=fps)
        stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
        stream.options = {'crf': '18', 'preset': 'veryfast'}
        for i in range(count):
            if name == 'same_color_layout_cut':
                pixels = np.full((height, width, 3), 24, np.uint8)
                pixels[:, :width // 2] = 224
                if i >= cut_frame:
                    pixels = pixels[:, ::-1].copy()
            elif name == 'brightness_cut':
                pixels = np.full((height, width, 3), 30 if i < cut_frame else 220, np.uint8)
            elif name == 'cross_content_cut':
                pixels = base if i < cut_frame else other
            elif name == 'two_frame_insert':
                pixels = np.full_like(base, 255) if cut_frame <= i < cut_frame + 2 else base
            elif name == 'flash_at_cut':
                pixels = base if i < cut_frame else np.full_like(base, 255) if i == cut_frame else other
            elif name == 'static_noise':
                noise = rng.integers(-3, 4, base.shape, dtype=np.int16)
                pixels = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
            elif name in {'slow_pan', 'fast_pan'}:
                offset = i * (1 if name == 'slow_pan' else 8)
                pixels = world[:, offset:offset + width].copy()
            elif name == 'single_frame_flash':
                pixels = np.full_like(base, 255) if i == cut_frame else base
            elif name == 'exposure_ramp':
                pixels = np.clip(base.astype(np.float32) * (.4 + .9 * i / (count - 1)), 0, 255).astype(np.uint8)
            else:
                alpha = float(np.clip((i / (count - 1) - .25) / .5, 0, 1))
                pixels = cv2.addWeighted(base, 1 - alpha, other, alpha, 0)
            frame = av.VideoFrame.from_ndarray(pixels, format='bgr24')
            frame.pts, frame.time_base = i, Fraction(1, fps)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return {'name': name, 'description': CASE_DESCRIPTIONS[name], 'video': path.name,
            'fps': fps, 'duration_seconds': duration, 'width': width, 'height': height,
            'seed': seed, 'expected_cuts': expected}


def run_benchmark(output_dir: Path, *, tolerance: float = .05, fps: int = 24,
                  cases: list[str] | None = None) -> dict[str, Any]:
    from selection.media import detect_range_scenes
    from video.scene_detect import detect_scenes
    from video.scene_features import SCENE_CUT_THRESHOLD, SCENE_DETECT_VERSION

    output_dir = Path(output_dir)
    match_cuts([], [], tolerance)  # Validate before writing any media.
    names = list(CASE_DESCRIPTIONS) if cases is None else cases
    if not names or any(name not in CASE_DESCRIPTIONS for name in names) or len(set(names)) != len(names):
        raise ValueError('Choose distinct, known benchmark cases')
    results = []
    for name in names:
        started = time.perf_counter()
        case = generate_case(output_dir, name, fps=fps)
        case['encoding_seconds'] = time.perf_counter() - started
        path = output_dir / case['video']
        for mode in ('full_video', 'selected_range'):
            started = time.perf_counter()
            if mode == 'full_video':
                shots = detect_scenes(path)
                detected = [shot['start'] for shot in shots[1:]]
            else:
                shots = detect_range_scenes(path, 0, case['duration_seconds'])
                detected = [shot.start for shot in shots[1:]]
            elapsed = time.perf_counter() - started
            case[mode] = {'detected_cuts': detected, 'elapsed_seconds': elapsed,
                          **match_cuts(case['expected_cuts'], detected, tolerance)}
        results.append(case)
    summary = {}
    for mode in ('full_video', 'selected_range'):
        totals = [sum(case[mode][key] for case in results)
                  for key in ('true_positives', 'false_positives', 'false_negatives')]
        summary[mode] = {**_metrics(*totals),
                         'elapsed_seconds': sum(case[mode]['elapsed_seconds'] for case in results)}
    report = {'schema_version': 1, 'detector_version': SCENE_DETECT_VERSION,
              'tolerance_seconds': tolerance,
              'scope': 'Synthetic hard-cut benchmark; does not estimate natural-video accuracy or gradual-transition recall.',
              'metric_convention': 'One-to-one inclusive tolerance; maximize matches then minimize total absolute time error. Both empty: P=R=F1=1. No truth: R=1; false predictions give P=F1=0. No predictions with truth: P=R=F1=0.',
              'detector_settings': {
                  'full_video_threshold': inspect.signature(detect_scenes).parameters['threshold'].default,
                  'full_video_min_shot_duration': inspect.signature(detect_scenes).parameters['min_shot_duration'].default,
                  'selected_range_threshold': SCENE_CUT_THRESHOLD,
                  'selected_range_min_shot_duration': None},
              'summary': summary, 'cases': results}
    (output_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output-dir', type=Path, required=True, help='Directory for synthetic media and report.json')
    parser.add_argument('--tolerance', type=float, default=.05, help='Inclusive hard-cut matching tolerance in seconds')
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--cases', nargs='+', choices=list(CASE_DESCRIPTIONS))
    args = parser.parse_args()
    try:
        report = run_benchmark(args.output_dir, tolerance=args.tolerance, fps=args.fps, cases=args.cases)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({'report': str((args.output_dir / 'report.json').resolve()),
                      'summary': report['summary']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
