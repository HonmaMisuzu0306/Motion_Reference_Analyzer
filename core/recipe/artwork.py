"""Bound artwork margins over the exported layer's piecewise-linear AE motion."""
from math import atan2, ceil, cos, degrees, hypot, isfinite, radians, sin

import numpy as np

from schemas.measured_motion import MotionSample

# Permit at most one extra pixel after outward integer rounding. If the coupled
# motion cannot be bounded tightly within the work budget, omit the suggestion.
BOUND_TOLERANCE_PX = .05
MAX_EXTRA_SPLITS = 4096
# Keep the unwrapped angle precise to better than one ten-millionth of a
# degree when bisecting. Extreme legacy values cannot support a tight bound.
MAX_ABS_DEGREES = 360_000_000
CARDINAL = {0: (1., 0.), 90: (0., 1.), 180: (-1., 0.), 270: (0., -1.)}


def _axes(angle):
    angle %= 360
    if angle in CARDINAL:
        return CARDINAL[angle]
    theta = radians(angle)
    return cos(theta), sin(theta)


def _bounds(first, last, half_width, half_height):
    """Return sampled lower bounds and conservative swept bounds on L/R/T/B.

    For any fixed frame corner, q = (corner - translation) / scale is on
    the line segment [q0,q1]: its weights are the two linear interpolation
    weights multiplied by the positive endpoint scales and renormalized.
    At any angle, each signed projection of q is therefore bounded by the
    larger projection of q0 and q1. For each endpoint vector we maximize its
    projection over the circular arc, including interior stationary angles.
    """
    dx0, dy0, s0, a0 = first
    dx1, dy1, s1, a1 = last
    c0, sn0 = _axes(a0)
    c1, sn1 = _axes(a1)
    low_angle = min(a0, a1) % 360
    sweep = abs(a1 - a0)
    half = (half_width, half_width, half_height, half_height)
    lower, upper = [0.] * 4, [0.] * 4
    for x in (-half_width, half_width):
        for y in (-half_height, half_height):
            for at_start, dx, dy, scale in ((True, dx0, dy0, s0), (False, dx1, dy1, s1)):
                qx, qy = (x - dx) / scale, (y - dy) / scale
                u0, v0 = c0 * qx + sn0 * qy, -sn0 * qx + c0 * qy
                u1, v1 = c1 * qx + sn1 * qy, -sn1 * qx + c1 * qy
                at0, at1 = (-u0, u0, -v0, v0), (-u1, u1, -v1, v1)
                radius = hypot(qx, qy)
                if not isfinite(radius):
                    return None
                phase = degrees(atan2(qy, qx))
                for i, peak_angle in enumerate((phase + 180, phase, phase + 90, phase - 90)):
                    actual = at0[i] if at_start else at1[i]
                    lower[i] = max(lower[i], actual - half[i])
                    peak_on_arc = sweep > 0 and (peak_angle - low_angle) % 360 <= sweep
                    maximum = radius if peak_on_arc else max(at0[i], at1[i])
                    upper[i] = max(upper[i], maximum - half[i])
    return lower, upper


def artwork_padding(trajectory: list[MotionSample], start: float, curves: list[dict],
                    width: int, height: int) -> dict[str, int] | None:
    """Bounds hold for the rendered linear curves, not unsampled source motion."""
    if len(trajectory) < 2 or not all(type(v) is int and 4 <= v <= 30000 for v in (width, height)):
        return None
    begin, end = trajectory[0].source_time - start, trajectory[-1].source_time - start
    if not isfinite(begin) or not isfinite(end) or begin >= end:
        return None
    times = sorted({begin, end, *(p['time'] for c in curves for p in c['points'] if begin < p['time'] < end)})
    channels = {}
    for curve in curves:
        points = curve['points']
        channels[curve['property']] = np.interp(times, [p['time'] for p in points], [p['value'] for p in points])
    with np.errstate(over='ignore', invalid='ignore'):
        poses = np.broadcast_arrays(channels.get('position_x', 0.) / 100 * width,
                                    channels.get('position_y', 0.) / 100 * height,
                                    channels.get('global_scale', 100.) / 100,
                                    channels.get('rotation', np.zeros(len(times))))
    poses = np.column_stack(poses)
    if (not np.isfinite(poses).all() or (poses[:, 2] <= 0).any()
            or np.max(np.abs(poses[:, 3])) > MAX_ABS_DEGREES):
        return None

    observed = [0.] * 4
    margins = [0.] * 4
    splits = 0
    previous = tuple(map(float, poses[0]))
    for row in poses[1:]:
        current = tuple(map(float, row))
        pending = [(previous, current)]
        previous = current
        while pending:
            first, last = pending.pop()
            bounds = _bounds(first, last, width / 2, height / 2)
            if bounds is None:
                return None
            lower, upper = bounds
            if width + lower[0] + lower[1] > 30000 or height + lower[2] + lower[3] > 30000:
                return None
            # At fixed angle (or fixed normalized corner vectors) the arc
            # calculation is exact. Otherwise refine any loosening that could
            # change the final integer dimensions by more than rounding noise.
            coupled = first[3] != last[3] and first[:3] != last[:3]
            observed = [max(old, value) for old, value in zip(observed, lower if coupled else upper)]
            if coupled and any(hi > confirmed + BOUND_TOLERANCE_PX and ceil(hi) > ceil(confirmed)
                               for hi, confirmed in zip(upper, observed)):
                if splits >= MAX_EXTRA_SPLITS:
                    return None
                middle = tuple(a / 2 + b / 2 for a, b in zip(first, last))
                if middle == first or middle == last:
                    return None
                splits += 1
                pending.extend(((middle, last), (first, middle)))
            else:
                margins = [max(old, hi) for old, hi in zip(margins, upper)]
    left, right, top, bottom = map(ceil, margins)
    total_width, total_height = width + left + right, height + top + bottom
    if total_width > 30000 or total_height > 30000:
        return None
    return {'left_px': left, 'right_px': right, 'top_px': top, 'bottom_px': bottom,
            'width_px': total_width, 'height_px': total_height}
