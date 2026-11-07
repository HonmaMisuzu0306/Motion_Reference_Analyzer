from typing import Any

from recipe.curves import active_channels, complete_trajectory
from recipe.keyframes import (
    RECIPE_VERSION,
    build_animation_plan,
    finite_number,
    reliable_measurement,
)


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def has_global_totals(status, trajectory_status, valid_pairs) -> bool:
    """Older endpoint records may lack counts; explicit gaps and zero pairs have no total."""
    return status in (None, 'ok') and trajectory_status != 'partial' and valid_pairs != 0


def shot_for_display(shot: dict, width: int, height: int) -> dict:
    """Derive an exportable plan for older records without overwriting stored evidence."""
    recipe = _mapping(shot.get('ae_recipe'))
    measured = _mapping(shot.get('measured_motion'))
    if recipe.get('version') == RECIPE_VERSION:
        return shot
    # Earlier releases measured padding only at sampled poses. Drop it from
    # the read view even when current evidence cannot yield a replacement.
    cached_plan = _mapping(recipe.get('animation_plan'))
    if 'artwork_padding' in cached_plan:
        cleaned = {key: value for key, value in cached_plan.items() if key != 'artwork_padding'}
        recipe = {**recipe, 'animation_plan': cleaned}
        shot = {**shot, 'ae_recipe': recipe}
    if (measured.get('trajectory_status') != 'complete'
            or measured.get('frame_width') != width or measured.get('frame_height') != height):
        return shot
    timing = _mapping(shot.get('time')) or {'start': shot.get('start_time'), 'end': shot.get('end_time')}
    # A library shot stores flat start/end fields. All three exports rebuild
    # from these observations; never use archived keyframes as new evidence.
    regenerated = generate_ae_recipe({'time': timing, 'measured_motion': measured,
                                      'motion_summary': _mapping(shot.get('motion_summary'))})
    plan = regenerated['animation_plan']
    if not plan['curves'] or plan['evidence_source'] != 'measured':
        if 'evidence_notice' in plan:
            archived_plan = {**_mapping(recipe.get('animation_plan')), 'evidence_notice': plan['evidence_notice']}
            return {**shot, 'ae_recipe': {**recipe, 'animation_plan': archived_plan}}
        return shot
    plan['notes'].append('关键帧试作方案按已保存的实测轨迹重新计算。')
    return {**shot, 'ae_recipe': {**recipe, 'animation_plan': plan}}


def generate_ae_recipe(shot: dict[str, Any]) -> dict[str, Any]:
    """基于 Shot 分析结果生成 AE Recipe 建议。

    输入来自 VisionAnalysis 的结构化字段，输出为 AE 制作建议。
    所有建议都基于视觉观察，不声称等同于原作者工程。
    """
    observations = _mapping(shot.get("observations"))
    motion = _mapping(shot.get("motion"))
    measured = _mapping(shot.get("measured_motion"))
    typography = _mapping(shot.get("typography"))
    typography_tracks = [track for track in (shot.get("typography_tracks") or []) if isinstance(track, dict)]
    effects = [effect for effect in (shot.get("visual_effects") or []) if isinstance(effect, dict)]
    hypothesis = _mapping(shot.get("ae_hypothesis"))

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
    if finite_number(observations.get("depth_layers")) > 1:
        layers.append({
            "role": "depth",
            "suggestion": f"{observations['depth_layers']} depth layers for parallax",
        })
    if typography.get("has_text") or typography_tracks:
        layers.append({
            "role": "typography",
            "suggestion": "独立文字图层",
        })

    camera = {
        "type": motion.get("type") or "unknown",
        "strength": max(0.0, min(finite_number(motion.get("strength")), 1.0)),
        "confidence": max(0.0, min(finite_number(motion.get("confidence")), 1.0)),
    }

    transform = {}
    measured_notes: list[str] = []

    # 优先使用 CV 客观测量值生成 Transform 参考
    trajectory = complete_trajectory(measured) if measured.get('trajectory_status') == 'complete' else []
    measured_reliable = reliable_measurement(measured, trajectory)
    if not measured_reliable:
        trajectory = []
    channels = active_channels(trajectory)
    if measured_reliable:
        scale_percent = finite_number(measured.get("scale_change_percent"))
        tx_ratio = finite_number(measured.get("translation_x_ratio"))
        ty_ratio = finite_number(measured.get("translation_y_ratio"))
        rotation_deg = finite_number(measured.get("rotation_deg"))

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
        if measured.get('trajectory_status') == 'complete':
            transform = {}
            for key, channel in channels.items():
                values = [point[1] for point in channel['points']]
                transform[key] = {'from': values[0], 'to': values[-1],
                                  'min_value': min(values), 'max_value': max(values)}

    # 如果 CV 不可用，回退到语义运动分类
    semantic_fallback = not measured_reliable and finite_number(camera['confidence']) >= 0.5
    strength = max(0.0, min(finite_number(camera['strength']), 1.0))
    if semantic_fallback and camera["type"] in {"push_in", "pull_out"}:
        direction = 1 if camera["type"] == "push_in" else -1
        transform["character_scale"] = {
            "from": 100,
            "to": 100 + int(direction * strength * 20),
        }
    elif semantic_fallback and camera["type"] in {"pan_left", "pan_right", "tilt_up", "tilt_down"}:
        axis = "position_x" if camera["type"] in {"pan_left", "pan_right"} else "position_y"
        direction = 1 if camera["type"] in {"pan_right", "tilt_down"} else -1
        transform[axis] = {
            "from": 0,
            "to": int(strength * 200 * direction),
        }

    for key, value in transform.items():
        value['basis'] = '全局运动测量近似' if measured_reliable else 'AI 方向判断的试作值'
        value['unit'] = (
            '缩放（%）' if key in {'global_scale', 'character_scale'} else
            '角度（°）' if key == 'rotation' else
            '画面宽度（%）' if measured_reliable and key == 'position_x' else
            '画面高度（%）' if measured_reliable and key == 'position_y' else '像素'
        )
    animation_plan = build_animation_plan(shot, transform, measured_reliable, trajectory, channels)

    typography_recipes: list[dict[str, Any]] = []
    if typography_tracks:
        for track in typography_tracks:
            analysis = _mapping(track.get("typography_analysis"))
            recipe = {
                "track_id": track.get("track_id") or None,
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
                    "时间范围为首次和末次识别到该文字的源视频时间。进出点请对照原片。"
                ),
            }
            typography_recipes.append(recipe)
    elif typography.get("has_text"):
        typography_recipes.append({
            "text": "unknown",
            "role": typography.get("style", "unknown"),
            "position": typography.get("position", "unknown"),
            "suggested_animation": {
                "hold": "按观察到的排版放置文字，对照原片确定进出方式。",
            },
            "notes": "根据代表帧的文字观察生成，缺少跨帧文字轨迹。",
        })

    effect_names = [e.get("type", "") for e in effects if finite_number(e.get("confidence")) > 0.5]

    result = {
        "version": RECIPE_VERSION,
        "layers": layers,
        "timing": {**_mapping(shot.get('rhythm')), 'notes': 'Measured cut alignment against estimated beats; not a claim about author intent.'},
        "camera": camera,
        "transform": transform,
        "animation_plan": animation_plan,
        "measured_motion": {
            "status": measured.get("status", "unknown"),
            **{key: measured[key] for key in ('confidence', 'message', 'valid_pair_count',
                                             'total_pair_count', 'spatially_limited_pair_count',
                                             'mixed_support_pair_count', 'long_baseline_check_count',
                                             'long_baseline_conflict_count') if key in measured},
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
    if has_global_totals(measured.get('status'), measured.get('trajectory_status'), measured.get('valid_pair_count')):
        aggregate_fields = ('scale_change_percent', 'translation_x_ratio', 'translation_y_ratio',
                            'rotation_deg', 'motion_strength')
        result['measured_motion'].update({key: measured[key] for key in aggregate_fields if key in measured})
    sampling_rate = finite_number(measured.get('sampling_target_fps'))
    if sampling_rate > 0:
        result['measured_motion']['sampling_target_fps'] = sampling_rate
    # Historical dictionaries may predate strict finite schemas. Unknown is null, never fake zero.
    from math import isfinite

    invalid_numbers = []

    def clean(value):
        if isinstance(value, float) and not isfinite(value):
            invalid_numbers.append(True)
            return None
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    result = clean(result)
    if invalid_numbers:
        result['animation_plan']['notes'].append('历史分析包含无效数值，已标为未知；请重新分析，不能将未知视为零运动。')
    return result


def _position_from_bbox(bbox: dict[str, Any]) -> str:
    """从归一化 bbox 推断位置标签。"""
    bbox = _mapping(bbox)
    x, y, w, h = (finite_number(bbox.get(key), float('nan')) for key in ('x', 'y', 'width', 'height'))
    from math import isfinite

    if (not all(isfinite(value) for value in (x, y, w, h)) or min(x, y) < 0 or w <= 0 or h <= 0
            or x + w > 1.000001 or y + h > 1.000001):
        return 'unknown'
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
    h = finite_number(_mapping(bbox).get("height"))
    if not 0 < h <= 1:
        return "unknown"
    return f"约 {h * 100:.1f}% 画面高度"


def _build_typography_keyframes(track: dict[str, Any]) -> dict[str, Any]:
    """根据运动和出现方式生成粗略的 Typography 关键帧建议。"""
    movement = track.get("movement", "unknown")
    appearance = track.get("appearance", "unknown")

    if finite_number(track.get("frame_count")) < 2 or not (
        finite_number(track.get("end_time")) > finite_number(track.get("start_time"))
    ):
        return {"hold": "按采样画面放置文字，逐帧核对进出点。"}

    suggestions = {}
    directions = {
        "slide_left": "向左", "slide_right": "向右",
        "slide_up": "向上", "slide_down": "向下",
    }
    if movement in directions:
        suggestions["position"] = f"在首末采样之间{directions[movement]}调整 Position，对齐文字中心。"
    elif movement in {"scale_in", "scale_out"}:
        direction = "增大" if movement == "scale_in" else "减小"
        suggestions["scale"] = f"依据首末采样的文字边界{direction} Scale。"

    if appearance == "fade":
        suggestions["opacity"] = "对照原片检查透明度变化后，再决定是否给 Opacity 加关键帧。"
    elif appearance == "mask_like_reveal":
        suggestions["in"] = "可试用蒙版或轨道遮罩，核对文字边缘的出现顺序。"
    elif appearance == "slide" and not suggestions:
        suggestions["position"] = "对齐各采样帧中的文字中心，核对 Position 的移动方向。"
    elif appearance == "scale" and "scale" not in suggestions:
        suggestions["scale"] = "对照文字边界变化调整 Scale。"
    return suggestions or {"hold": "在识别区间内保持文字可见，按原片设置图层入点和出点。"}
