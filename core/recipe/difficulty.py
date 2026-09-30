from typing import Any


def estimate_difficulty(recipe: dict[str, Any]) -> dict[str, Any]:
    """估算 AE 制作难度。"""
    layers = recipe.get("layers", [])
    effects = recipe.get("effects", [])
    camera = recipe.get("camera", {})

    layer_score = min(len(layers) * 1, 5)
    effect_score = min(len(effects) * 1, 5)
    camera_score = 1 if camera.get("type") != "static" else 0

    total = layer_score + effect_score + camera_score
    stars = min(max(int(total), 1), 5)

    return {
        "ae": "★" * stars + "☆" * (5 - stars),
        "ae_numeric": stars,
        "needs_blender": False,
        "needs_layering": len(layers) > 1,
        "mad_suitable": stars <= 4,
    }
