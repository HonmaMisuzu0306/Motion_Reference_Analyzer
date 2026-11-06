"""Time-aware descriptive motion scores, not calibrated probabilities.

Stability describes local trajectory smoothness. Shake requires repeated,
nontrivial direction reversals; a large one-way pan is not shake evidence.
Scores describe measured global 2D motion and cannot establish artistic intent.
"""
from itertools import groupby

import numpy as np

from schemas.measured_motion import MotionSample

# Dead zones are in original pixels, log scale (~0.1%), and degrees.
MIN_CENTER_NOISE_PX = 0.5
CENTER_NOISE_FRAME_RATIO = 0.001
LOG_SCALE_NOISE = 0.001
ROTATION_NOISE_DEG = 0.1
MIN_REVERSALS_PER_SECOND = 1.0
STRONG_REVERSALS_PER_SECOND = 2.5


def _reversal_score(values: np.ndarray, times: np.ndarray, noise: float) -> float:
    """Require multiple swings, sufficient amplitude, and temporal frequency."""
    runs: list[tuple[int, float]] = []
    for delta in np.diff(values):
        if abs(delta) <= noise:
            continue
        direction = 1 if delta > 0 else -1
        if runs and runs[-1][0] == direction:
            runs[-1] = direction, runs[-1][1] + abs(float(delta))
        else:
            runs.append((direction, abs(float(delta))))
    reversals = len(runs) - 1
    if reversals < 2:
        return 0.0
    duration = float(times[-1] - times[0])
    frequency = reversals / duration
    frequency_score = np.clip((frequency - MIN_REVERSALS_PER_SECOND)
                              / (STRONG_REVERSALS_PER_SECOND - MIN_REVERSALS_PER_SECOND), 0, 1)
    # One deliberate turnaround gives zero. Two reversals alone cannot give 1.
    count_score = min(1.0, (reversals - 1) / 2)
    amplitudes = [min(left[1], right[1]) for left, right in zip(runs, runs[1:])]
    amplitude_score = float(np.mean(np.clip((np.asarray(amplitudes) - noise) / (3 * noise), 0, 1)))
    return float(frequency_score * count_score * amplitude_score)


def motion_quality(trajectory: list[MotionSample], *, frame_width: int,
                   frame_height: int) -> tuple[float, float]:
    """Return (stability, shake) using center positions and actual presentation times.

    An interior point's interpolation residual is the change in velocity times
    dt_left*dt_right/(dt_left+dt_right). Constant velocities thus remain stable
    with VFR sampling. Noise is removed before normalizing by local displacement,
    so near-zero rotation/scale do not magnify estimation noise. Segments are
    evaluated independently; missing tracking never creates a reversal.
    """
    if min(frame_width, frame_height) <= 0:
        raise ValueError('Frame dimensions must be positive')
    if not trajectory:
        return 0.0, 0.0
    pixel_noise = max(MIN_CENTER_NOISE_PX, min(frame_width, frame_height) * CENTER_NOISE_FRAME_RATIO)
    roughness, weights, shakes = [], [], []
    for _, points_iter in groupby(trajectory, key=lambda point: (point.segment_id, point.segment_start_time)):
        points = list(points_iter)
        if len(points) < 2:
            continue
        times = np.array([point.source_time for point in points])
        dt = np.diff(times)
        if np.any(dt <= 0):
            raise ValueError('Trajectory timestamps must strictly increase within each segment')
        values = np.array([[point.translation_x_px, point.translation_y_px,
                            np.log(point.scale_ratio), point.rotation_deg] for point in points])
        if not np.all(np.isfinite(values)) or not np.all(np.isfinite(times)):
            raise ValueError('Trajectory values must be finite')
        steps = np.diff(values, axis=0)
        velocities = steps / dt[:, None]
        if len(points) >= 3:
            residual = np.abs(np.diff(velocities, axis=0)) * (dt[:-1] * dt[1:] / (dt[:-1] + dt[1:]))[:, None]
            center_residual = np.linalg.norm(residual[:, :2], axis=1)
            center_steps = np.linalg.norm(steps[:, :2], axis=1)
            local_center = (center_steps[:-1] + center_steps[1:]) / 2
            penalties = [np.maximum(center_residual - pixel_noise, 0) / (pixel_noise + local_center)]
            for column, noise in ((2, LOG_SCALE_NOISE), (3, ROTATION_NOISE_DEG)):
                local_step = (np.abs(steps[:-1, column]) + np.abs(steps[1:, column])) / 2
                penalties.append(np.maximum(residual[:, column] - noise, 0) / (noise + local_step))
            roughness.extend(np.max(penalties, axis=0))
            weights.extend((dt[:-1] + dt[1:]) / 2)
        shakes.append(max(_reversal_score(values[:, column], times, noise) for column, noise in (
            (0, pixel_noise), (1, pixel_noise), (2, LOG_SCALE_NOISE), (3, ROTATION_NOISE_DEG))))
    instability = float(np.average(roughness, weights=weights)) if weights else 0.0
    return float(np.clip(1 - 2 * instability, 0, 1)), max(shakes, default=0.0)
