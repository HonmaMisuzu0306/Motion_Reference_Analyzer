from typing import Any


def generate_ae_recipe(shot: dict[str, Any]) -> dict[str, Any]:
    """基于 Shot 分析结果生成 AE Recipe 建议。"""
    observations = shot.get("observations", {})
    motion = shot.get("motion", {})
    typography = shot.get("typography", {})
    effects = shot.get("visual_effects", [])

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
    if typography.get("has_text"):
        layers.append({
            "role": "typography",
            "suggestion": "text layer with mask reveal",
        })

    camera = {
        "type": motion.get("type", "static"),
        "strength": motion.get("strength", 0.0),
    }

    transform = {}
    if camera["type"] in {"push_in", "pull_out"}:
        transform["character_scale"] = {
            "from": 100,
            "to": 100 + int(camera["strength"] * 20),
        }

    typography_recipe = {}
    if typography.get("has_text"):
        typography_recipe = {
            "method": "mask_reveal",
            "duration": 0.35,
        }

    effect_names = [e.get("name", "") for e in effects if e.get("confidence", 0) > 0.5]

    return {
        "layers": layers,
        "camera": camera,
        "transform": transform,
        "typography": typography_recipe,
        "effects": effect_names,
    }
