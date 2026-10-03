from typing import Any


def generate_ae_recipe(shot: dict[str, Any]) -> dict[str, Any]:
    """基于 Shot 分析结果生成 AE Recipe 建议。

    输入来自 VisionAnalysis 的结构化字段，输出为 AE 制作建议。
    所有建议都基于视觉观察，不声称等同于原作者工程。
    """
    observations = shot.get("observations", {})
    motion = shot.get("motion", {})
    measured = shot.get("measured_motion", {})
    typography = shot.get("typography", {})
    typography_tracks = shot.get("typography_tracks", [])
    effects = shot.get("visual_effects", [])
    hypothesis = shot.get("ae_hypothesis", {})

    layers = []
    if observations.get("background_type") not in {"unknown", None}:
        layers.append({
            "role": "background",
            "suggestion": "separate background layer",
        })
    if observations.get("subject_type") in {"character", "object", "mixed"}:
        layers.append({
            "role": "character",
            "suggestion": "isolated character/object layer",
        })
    if observations.get("depth_layers") and observations["depth_layers"] > 1:
        layers.append({
            "role": "depth",
            "suggestion": f"{observations['depth_layers']} depth layers for parallax",
        })
    if typography.get("has_text") or typography_tracks:
        layers.append({
            "role": "typography",
            "suggestion": "text layer with mask reveal",
        })

    camera = {
        "type": motion.get("type", "static"),
        "strength": motion.get("strength", 0.0),
        "confidence": motion.get("confidence", 0.0),
    }

    transform = {}
    measured_notes: list[str] = []

    # 优先使用 CV 客观测量值生成 Transform 参考
    if measured.get("status") == "ok":
        scale_percent = measured.get("scale_change_percent", 0.0)
        tx_ratio = measured.get("translation_x_ratio", 0.0)
        ty_ratio = measured.get("translation_y_ratio", 0.0)
        rotation_deg = measured.get("rotation_deg", 0.0)

        if abs(scale_percent) >= 0.5:
            transform["global_scale"] = {
                "from": 100,
                "to": round(100 + scale_percent, 1),
            }
            measured_notes.append(
                f"Global scale change measured: {scale_percent:+.1f}%"
            )

        if abs(tx_ratio) >= 0.005:
            transform["position_x"] = {
                "from": 0,
                "to": round(tx_ratio * 100, 2),
            }
            measured_notes.append(
                f"Horizontal translation measured: {tx_ratio * 100:+.2f}%"
            )

        if abs(ty_ratio) >= 0.005:
            transform["position_y"] = {
                "from": 0,
                "to": round(ty_ratio * 100, 2),
            }
            measured_notes.append(
                f"Vertical translation measured: {ty_ratio * 100:+.2f}%"
            )

        if abs(rotation_deg) >= 0.5:
            transform["rotation"] = {
                "from": 0,
                "to": round(rotation_deg, 2),
            }
            measured_notes.append(f"Rotation measured: {rotation_deg:+.2f}°")

        measured_notes.append("Approximation from measured global motion, not exact AE params.")

    # 如果 CV 不可用，回退到语义运动分类
    if not transform and camera["type"] in {"push_in", "pull_out"}:
        direction = 1 if camera["type"] == "push_in" else -1
        transform["character_scale"] = {
            "from": 100,
            "to": 100 + int(direction * camera["strength"] * 20),
        }
    elif not transform and camera["type"] in {"pan_left", "pan_right"}:
        transform["position_x"] = {
            "from": 0,
            "to": int(camera["strength"] * 200 * (1 if camera["type"] == "pan_right" else -1)),
        }

    typography_recipes: list[dict[str, Any]] = []
    if typography_tracks:
        for track in typography_tracks:
            analysis = track.get("typography_analysis") or {}
            recipe = {
                "text": track.get("canonical_text", ""),
                "role": analysis.get("role", "unknown"),
                "start_time": track.get("start_time", 0.0),
                "end_time": track.get("end_time", 0.0),
                "duration": track.get("duration", 0.0),
                "position": _position_from_bbox(track.get("average_bbox", {})),
                "alignment": analysis.get("alignment", "unknown"),
                "style_family": analysis.get("style_family", "unknown"),
                "weight": analysis.get("weight", "unknown"),
                "tracking": analysis.get("tracking", "unknown"),
                "motion": track.get("movement", "unknown"),
                "appearance": track.get("appearance", "unknown"),
                "estimated_size": _estimate_size(track.get("average_bbox", {})),
                "suggested_animation": _build_typography_keyframes(track),
                "notes": (
                    "Approximation from rendered footage. "
                    "Not a claim about the original AE project."
                ),
            }
            typography_recipes.append(recipe)
    elif typography.get("has_text"):
        typography_recipes.append({
            "text": "unknown",
            "role": typography.get("style", "unknown"),
            "position": typography.get("position", "unknown"),
            "suggested_animation": {
                "in": "Opacity Fade",
                "out": "Opacity Fade",
            },
            "notes": "Legacy vision typography fallback.",
        })

    effect_names = [e.get("type", "") for e in effects if e.get("confidence", 0) > 0.5]

    return {
        "layers": layers,
        "timing": {**shot.get('rhythm', {}), 'notes': 'Measured cut alignment against estimated beats; not a claim about author intent.'},
        "camera": camera,
        "transform": transform,
        "measured_motion": {
            "status": measured.get("status", "unknown"),
            "scale_change_percent": measured.get("scale_change_percent", 0.0),
            "translation_x_ratio": measured.get("translation_x_ratio", 0.0),
            "translation_y_ratio": measured.get("translation_y_ratio", 0.0),
            "rotation_deg": measured.get("rotation_deg", 0.0),
            "motion_strength": measured.get("motion_strength", "none"),
            "confidence": measured.get("confidence", 0.0),
            "notes": measured_notes,
        },
        "typography": typography_recipes,
        "effects": effect_names,
        "hypothesis": {
            "possible_method": hypothesis.get("possible_method", "unknown"),
            "possible_effect": hypothesis.get("possible_effect", "unknown"),
            "possible_transition": hypothesis.get("possible_transition", "unknown"),
            "notes": hypothesis.get("notes", ""),
        },
    }


def _position_from_bbox(bbox: dict[str, Any]) -> str:
    """从归一化 bbox 推断位置标签。"""
    x = bbox.get("x", 0.0)
    y = bbox.get("y", 0.0)
    w = bbox.get("width", 0.0)
    h = bbox.get("height", 0.0)
    cx = x + w / 2
    cy = y + h / 2

    horizontal = "center"
    if cx < 0.35:
        horizontal = "left"
    elif cx > 0.65:
        horizontal = "right"

    vertical = "center"
    if cy < 0.35:
        vertical = "top"
    elif cy > 0.65:
        vertical = "bottom"

    if vertical == "center":
        return horizontal
    if horizontal == "center":
        return vertical
    return f"{vertical}_{horizontal}"


def _estimate_size(bbox: dict[str, Any]) -> str:
    """估算文字高度占画面的比例。"""
    h = bbox.get("height", 0.0)
    if h <= 0:
        return "unknown"
    return f"约 {h * 100:.1f}% 画面高度"


def _build_typography_keyframes(track: dict[str, Any]) -> dict[str, Any]:
    """根据运动和出现方式生成粗略的 Typography 关键帧建议。"""
    movement = track.get("movement", "unknown")
    appearance = track.get("appearance", "unknown")

    keyframes: dict[str, Any] = {
        "in": "Opacity 0 → 100",
        "hold": "保持可见",
        "out": "Opacity 100 → 0",
    }

    if movement == "slide_right":
        keyframes["in"] = "Position X offset left → 0"
    elif movement == "slide_left":
        keyframes["in"] = "Position X offset right → 0"
    elif movement == "slide_up":
        keyframes["in"] = "Position Y offset below → 0"
    elif movement == "slide_down":
        keyframes["in"] = "Position Y offset above → 0"
    elif movement == "scale_in":
        keyframes["in"] = "Scale 0% → 100%"
    elif movement == "scale_out":
        keyframes["out"] = "Scale 100% → 0%"

    if appearance == "fade":
        keyframes["in"] = "Opacity 0 → 100"
    elif appearance == "scale":
        keyframes["in"] = "Scale 0% → 100%"
    elif appearance == "slide":
        if "Position" not in keyframes["in"]:
            keyframes["in"] = "Position offset → 0"
    elif appearance == "mask_like_reveal":
        keyframes["in"] = "Mask Reveal / Track Matte (Hypothesis)"

    return keyframes
