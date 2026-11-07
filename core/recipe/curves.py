"""Sample-time animation curves with bounded linear reconstruction error."""
from math import cos, isclose, isfinite, radians, sin

from pydantic import ValidationError

from schemas.measured_motion import MeasuredMotion, MotionSample

CURVE_PROPERTIES = {
    'position_x': ('translation_x_ratio', 100, '画面宽度（%）', .5, .1),
    'position_y': ('translation_y_ratio', 100, '画面高度（%）', .5, .1),
    'global_scale': ('scale_ratio', 100, '缩放（%）', .5, .2),
    'rotation': ('rotation_deg', 1, '角度（°）', .5, .1),
}


def _consistent_sample(point: MotionSample, width: int, height: int) -> bool:
    """Cross-check redundant coordinates before treating them as AE properties."""
    (a, b, tx), (c, d, ty) = point.matrix
    expected_x = a * (width / 2) + b * (height / 2) + tx - width / 2
    expected_y = c * (width / 2) + d * (height / 2) + ty - height / 2
    if not all(isfinite(value) for value in (expected_x, expected_y)):
        return False
    if not all(isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-6) for actual, expected in (
        (point.translation_x_px, expected_x), (point.translation_y_px, expected_y),
        (point.translation_x_ratio, point.translation_x_px / width),
        (point.translation_y_ratio, point.translation_y_px / height),
    )):
        return False
    # Resizing may use slightly different x/y factors. Diagonals and b*c remain
    # invariant under that coordinate conversion, unlike either off-diagonal alone.
    angle = radians(point.rotation_deg % 360)
    diagonal, cross = cos(angle), sin(angle)
    a, b, c, d = (item / point.scale_ratio for item in (a, b, c, d))
    if not all(isfinite(item) for item in (a, b, c, d, b * c)):
        return False
    return (
        isclose(a, diagonal, rel_tol=1e-7, abs_tol=1e-7)
        and isclose(d, diagonal, rel_tol=1e-7, abs_tol=1e-7)
        and isclose(-b * c, cross * cross, rel_tol=1e-7, abs_tol=1e-7)
        and (abs(cross) <= 1e-7 or (b * cross < 0 and c * cross > 0))
        and (abs(cross) > 1e-7 or max(abs(b), abs(c)) <= 1e-6)
    )


def complete_trajectory(measured: dict) -> list[MotionSample]:
    """Return only a consistent, center-referenced segment starting at identity."""
    try:
        value = MeasuredMotion.model_validate(measured)
        if not all(isfinite(float(dimension)) for dimension in (value.frame_width, value.frame_height)):
            return []
    except (ValidationError, TypeError, OverflowError):
        return []
    points = value.trajectory
    if (value.trajectory_status != 'complete' or value.translation_reference != 'frame_center'
            or min(value.frame_width, value.frame_height) <= 0 or len(points) < 3
            or value.sample_count != len(points) or value.valid_pair_count != len(points) - 1
            or value.total_pair_count != value.valid_pair_count):
        return []
    first = points[0]
    if (abs(first.translation_x_ratio) > 1e-8 or abs(first.translation_y_ratio) > 1e-8
            or abs(first.scale_ratio - 1) > 1e-8 or abs(first.rotation_deg) > 1e-8
            or first.segment_start_time != first.source_time):
        return []
    if (any(p.segment_id != first.segment_id or p.segment_start_time != first.source_time for p in points)
            or any(a.source_time >= b.source_time for a, b in zip(points, points[1:]))):
        return []
    if any(not _consistent_sample(point, value.frame_width, value.frame_height) for point in points):
        return []
    # Summaries are rounded by the analyzer; allow only its documented precision.
    last = points[-1]
    if any(not isclose(actual, expected, rel_tol=1e-9, abs_tol=tolerance) for actual, expected, tolerance in (
        (value.translation_x_px, last.translation_x_px, .00500001),
        (value.translation_y_px, last.translation_y_px, .00500001),
        (value.translation_x_ratio, last.translation_x_ratio, .0000500001),
        (value.translation_y_ratio, last.translation_y_ratio, .0000500001),
        (value.scale_ratio, last.scale_ratio, .0000500001),
        (value.scale_change_percent, (last.scale_ratio - 1) * 100, .00500001),
        (value.rotation_deg, last.rotation_deg, .00500001),
    )):
        return []
    if value.pairs and (len(value.pairs) != value.total_pair_count or any(
        not pair.valid or pair.start_time != left.source_time or pair.end_time != right.source_time
        for pair, left, right in zip(value.pairs, points, points[1:])
    )):
        return []
    if value.pairs and any(
        pair.scale_ratio <= 0
        or not isclose(left.scale_ratio * pair.scale_ratio, right.scale_ratio, rel_tol=1e-7, abs_tol=1e-8)
        or not isclose(left.rotation_deg + pair.rotation_deg, right.rotation_deg, rel_tol=1e-9, abs_tol=1e-7)
        for pair, left, right in zip(value.pairs, points, points[1:])
    ):
        return []
    # Finite stored values can still overflow while being converted into AE units.
    for attribute, multiplier, *_ in CURVE_PROPERTIES.values():
        values = [getattr(point, attribute) * multiplier for point in points]
        if not all(isfinite(item) for item in values) or not isfinite(max(values) - min(values)):
            return []
    return points


def active_channels(points: list[MotionSample]) -> dict:
    channels = {}
    for key, (attribute, multiplier, unit, minimum_range, tolerance) in CURVE_PROPERTIES.items():
        values = [getattr(point, attribute) * multiplier for point in points]
        if values and max(values) - min(values) >= minimum_range:
            channels[key] = {'points': [(p.source_time, value) for p, value in zip(points, values)],
                             'unit': unit, 'tolerance': tolerance}
    return channels


def simplify_curve(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Keep measured samples until every omitted value meets a time-based error bound."""
    if not isfinite(tolerance) or tolerance <= 0:
        raise ValueError('曲线容差必须为有限正数')
    if any(not isfinite(t) or not isfinite(value) for t, value in points):
        raise ValueError('曲线时间和数值必须有限')
    if any(a[0] >= b[0] for a, b in zip(points, points[1:])):
        raise ValueError('曲线时间必须严格递增')
    if len(points) < 3:
        return list(points)
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        left, right = pending.pop()
        if right - left < 2:
            continue
        t0, v0 = points[left]
        t1, v1 = points[right]
        def fraction(time):
            span = t1 - t0
            if isfinite(span):
                return (time - t0) / span
            return (time / 2 - t0 / 2) / (t1 / 2 - t0 / 2)

        errors = [(abs(points[i][1] - ((1 - fraction(points[i][0])) * v0
                                     + fraction(points[i][0]) * v1)), i)
                  for i in range(left + 1, right)]
        error, split = max(errors, key=lambda pair: (pair[0], -abs(pair[1] - (left + right) / 2)))
        if error > tolerance:
            keep.add(split)
            pending.extend([(left, split), (split, right)])
    return [points[index] for index in sorted(keep)]


def animation_curves(measured: dict, start: float, end: float) -> list[dict]:
    if not all(isfinite(value) for value in (start, end)) or not 0 <= start < end:
        return []
    trajectory = complete_trajectory(measured)
    if not trajectory or trajectory[0].source_time < start or trajectory[-1].source_time >= end:
        return []
    return curves_from_channels(active_channels(trajectory), start)


def curves_from_channels(channels: dict, start: float) -> list[dict]:
    curves = []
    for key, channel in channels.items():
        reduced = simplify_curve(channel['points'], channel['tolerance'])
        curves.append({
            'property': key, 'unit': channel['unit'], 'basis': '连续全局运动测量',
            'interpolation': 'linear', 'tolerance': channel['tolerance'],
            'sample_count': len(channel['points']), 'keyframe_count': len(reduced),
            'points': [{'time': time - start, 'value': value} for time, value in reduced],
        })
    return curves
