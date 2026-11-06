from math import isfinite
from typing import Any

from cv.thresholds import (
    FUSION_ROTATION_THRESHOLD_DEG,
    FUSION_SCALE_THRESHOLD_PERCENT,
    FUSION_SHAKE_THRESHOLD,
    FUSION_TRANSLATION_THRESHOLD_RATIO,
)
from schemas.measured_motion import MeasuredMotion

MIN_MEASURED_CONFIDENCE = 0.5


def _confidence(value: Any) -> float:
    """Keep old/dictionary inputs from turning unavailable evidence into NaN confidence."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(result, 1.0)) if isfinite(result) else 0.0


def _motion_signal(values: list[float], threshold: float, positive: str,
                   negative: str) -> tuple[str, float] | None:
    """Compare dimensionless strength and retain excursions hidden by a zero endpoint."""
    span = max(values) - min(values)
    if span <= threshold:
        return None

    minimum = maximum = values[0]
    rise = fall = 0.0
    for value in values[1:]:
        rise = max(rise, value - minimum)
        fall = max(fall, maximum - value)
        minimum, maximum = min(minimum, value), max(maximum, value)
    if rise > threshold and fall > threshold:
        return 'complex', span / threshold

    delta = values[-1] - values[0]
    if abs(delta) <= threshold:
        delta = max(values, key=lambda value: abs(value - values[0])) - values[0]
    return (positive if delta > 0 else negative), span / threshold


def _measured_signals(measured: MeasuredMotion) -> list[tuple[str, float]] | None:
    if measured.trajectory_status == 'complete':
        samples = measured.trajectory
        # Segment references cannot be compared or joined across an unobserved gap.
        if (len(samples) < 2 or len({sample.segment_id for sample in samples}) != 1
                or len({sample.segment_start_time for sample in samples}) != 1
                or any(right.source_time <= left.source_time for left, right in zip(samples, samples[1:]))):
            return None
        scale = [(sample.scale_ratio / samples[0].scale_ratio - 1) * 100 for sample in samples]
        x = [sample.translation_x_ratio for sample in samples]
        y = [sample.translation_y_ratio for sample in samples]
        # Successive valid pair rotations are bounded; unwrap atan2's +/-180 branch.
        rotation = [samples[0].rotation_deg]
        for left, right in zip(samples, samples[1:]):
            rotation.append(rotation[-1] + (right.rotation_deg - left.rotation_deg + 180) % 360 - 180)
    else:
        # Legacy records may have reliable endpoint measurements but no trajectory.
        scale = [0.0, measured.scale_change_percent]
        x = [0.0, measured.translation_x_ratio]
        y = [0.0, measured.translation_y_ratio]
        rotation = [0.0, measured.rotation_deg]

    if not all(isfinite(value) for values in (scale, x, y, rotation) for value in values):
        return None
    candidates = [
        _motion_signal(scale, FUSION_SCALE_THRESHOLD_PERCENT, 'push_in', 'pull_out'),
        _motion_signal(x, FUSION_TRANSLATION_THRESHOLD_RATIO, 'pan_right', 'pan_left'),
        _motion_signal(y, FUSION_TRANSLATION_THRESHOLD_RATIO, 'tilt_down', 'tilt_up'),
        _motion_signal(rotation, FUSION_ROTATION_THRESHOLD_DEG, 'rotation', 'rotation'),
    ]
    return [signal for signal in candidates if signal is not None]


def _infer_measured_semantic_type(measured: MeasuredMotion) -> str:
    """从客观测量值推断最可能对应的运动语义标签。"""
    if (measured.status != "ok" or measured.trajectory_status == 'partial'
            or _confidence(measured.confidence) < MIN_MEASURED_CONFIDENCE):
        return "unknown"

    signals = _measured_signals(measured)
    if signals is None:
        return 'unknown'
    if measured.shake_score >= FUSION_SHAKE_THRESHOLD:
        return "shake"

    if not signals:
        return "static"

    signals.sort(key=lambda x: x[1], reverse=True)
    return signals[0][0]


def fuse_motion(
    semantic_motion: dict[str, Any],
    measured: MeasuredMotion,
) -> dict[str, Any]:
    """融合 VLM 语义运动与 CV 客观测量运动。

    当语义判断与测量结果一致时提升置信度；
    当发生冲突时保留冲突标记，不偷偷覆盖语义标签。
    """
    semantic_type = semantic_motion.get("type", "unknown")
    semantic_confidence = _confidence(semantic_motion.get("confidence", 0.0))
    measured_confidence = _confidence(measured.confidence)
    measured_type = _infer_measured_semantic_type(measured)

    conflict = False
    confidence_boost = 0.0

    if measured_type == "unknown":
        # CV 测量失败，保留语义判断，但降低总体置信度
        fused_confidence = round(semantic_confidence * 0.8, 3)
    elif semantic_type == "unknown":
        # 没有语义判断时，直接采用测量推断
        fused_confidence = round(measured_confidence, 3)
    elif semantic_type == measured_type:
        confidence_boost = 0.1
        fused_confidence = round(min(semantic_confidence + confidence_boost, 1.0), 3)
    elif semantic_type == "static" and measured_type != "static":
        conflict = True
        fused_confidence = round(semantic_confidence * 0.7, 3)
    elif measured_type == "static" and semantic_type != "static":
        # 语义判断有运动，但测量为静止，可能是真实静止或低纹理
        conflict = True
        fused_confidence = round(min(semantic_confidence, measured_confidence), 3)
    else:
        conflict = True
        fused_confidence = round((semantic_confidence + measured_confidence) / 2.0, 3)

    return {
        "semantic_type": semantic_type,
        "semantic_confidence": semantic_confidence,
        "measured_type": measured_type,
        "measured_confidence": round(measured_confidence, 3),
        "fused_type": semantic_type if semantic_type != "unknown" else measured_type,
        "fused_confidence": fused_confidence,
        "conflict": conflict,
        "measured_status": measured.status,
    }
