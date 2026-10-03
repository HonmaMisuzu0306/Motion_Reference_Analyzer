from typing import Any

from cv.thresholds import (
    FUSION_ROTATION_THRESHOLD_DEG,
    FUSION_SCALE_THRESHOLD_PERCENT,
    FUSION_SHAKE_THRESHOLD,
    FUSION_TRANSLATION_THRESHOLD_RATIO,
)
from schemas.measured_motion import MeasuredMotion


def _infer_measured_semantic_type(measured: MeasuredMotion) -> str:
    """从客观测量值推断最可能对应的运动语义标签。"""
    if measured.status != "ok":
        return "unknown"

    if measured.shake_score >= FUSION_SHAKE_THRESHOLD:
        return "shake"

    scale_delta = measured.scale_change_percent
    tx = measured.translation_x_ratio
    ty = measured.translation_y_ratio
    rot = measured.rotation_deg

    signals: list[tuple[str, float]] = []

    if scale_delta > FUSION_SCALE_THRESHOLD_PERCENT:
        signals.append(("push_in", abs(scale_delta)))
    elif scale_delta < -FUSION_SCALE_THRESHOLD_PERCENT:
        signals.append(("pull_out", abs(scale_delta)))

    if tx > FUSION_TRANSLATION_THRESHOLD_RATIO:
        signals.append(("pan_right", abs(tx)))
    elif tx < -FUSION_TRANSLATION_THRESHOLD_RATIO:
        signals.append(("pan_left", abs(tx)))

    if ty > FUSION_TRANSLATION_THRESHOLD_RATIO:
        signals.append(("tilt_down", abs(ty)))
    elif ty < -FUSION_TRANSLATION_THRESHOLD_RATIO:
        signals.append(("tilt_up", abs(ty)))

    if abs(rot) > FUSION_ROTATION_THRESHOLD_DEG:
        signals.append(("rotation", abs(rot) / 10.0))

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
    semantic_confidence = float(semantic_motion.get("confidence", 0.0))
    measured_type = _infer_measured_semantic_type(measured)

    conflict = False
    confidence_boost = 0.0

    if measured.status != "ok":
        # CV 测量失败，保留语义判断，但降低总体置信度
        fused_confidence = round(semantic_confidence * 0.8, 3)
    elif semantic_type == "unknown":
        # 没有语义判断时，直接采用测量推断
        fused_confidence = round(measured.confidence, 3)
    elif semantic_type == measured_type:
        confidence_boost = 0.1
        fused_confidence = round(min(semantic_confidence + confidence_boost, 1.0), 3)
    elif semantic_type == "static" and measured_type != "static":
        conflict = True
        fused_confidence = round(semantic_confidence * 0.7, 3)
    elif measured_type == "static" and semantic_type != "static":
        # 语义判断有运动，但测量为静止，可能是真实静止或低纹理
        conflict = True
        fused_confidence = round(min(semantic_confidence, measured.confidence), 3)
    else:
        conflict = True
        fused_confidence = round((semantic_confidence + measured.confidence) / 2.0, 3)

    return {
        "semantic_type": semantic_type,
        "semantic_confidence": semantic_confidence,
        "measured_type": measured_type,
        "measured_confidence": round(measured.confidence, 3),
        "fused_type": semantic_type if semantic_type != "unknown" else measured_type,
        "fused_confidence": fused_confidence,
        "conflict": conflict,
        "measured_status": measured.status,
    }
