from typing import Any


def classify_camera_motion(motion: dict[str, Any]) -> dict[str, Any]:
    """根据相机运动参数分类运动类型。"""
    scale_ratio = motion.get("scale_ratio", 1.0)
    tx = motion.get("translation_x", 0.0)
    ty = motion.get("translation_y", 0.0)
    rotation_deg = motion.get("rotation_deg", 0.0)
    confidence = motion.get("confidence", 0.0)

    scale_delta = (scale_ratio - 1.0) * 100

    motion_type = "static"
    strength = 0.0

    if abs(scale_delta) > 1.0:
        motion_type = "push_in" if scale_delta > 0 else "pull_out"
        strength = min(abs(scale_delta) / 10.0, 1.0)
    elif abs(tx) > 5.0 or abs(ty) > 5.0:
        if abs(tx) > abs(ty):
            motion_type = "pan_right" if tx > 0 else "pan_left"
        else:
            motion_type = "tilt_down" if ty > 0 else "tilt_up"
        strength = min(max(abs(tx), abs(ty)) / 50.0, 1.0)
    elif abs(rotation_deg) > 1.0:
        motion_type = "rotation"
        strength = min(abs(rotation_deg) / 10.0, 1.0)

    return {
        "type": motion_type,
        "strength": round(strength, 3),
        "confidence": round(confidence, 3),
        "description": f"{motion_type} (strength={strength:.2f})",
    }
