"""Turn qualified motion evidence into an explicitly approximate AE starting point."""
from math import isfinite
from typing import Any

from recipe.artwork import artwork_padding
from recipe.curves import curves_from_channels
from schemas.measured_motion import MotionSample

RECIPE_VERSION = 'ae-recipe-v7-spatial-support'
LEGACY_SPATIAL_NOTICE = '这条轨迹未记录每个帧对的跟踪点分布，无法核实是否覆盖整幅画面。建议重新分析原片后再按全局运动试作。'
MIN_MEASURED_CONFIDENCE = 0.5


def finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def reliable_measurement(measured: dict, trajectory: list[MotionSample]) -> bool:
    if not isinstance(measured, dict):
        return False
    confidence = finite_number(measured.get('confidence'))
    return (
        measured.get('status') == 'ok'
        and measured.get('trajectory_status') in {None, 'not_measured', 'complete'}
        and (measured.get('trajectory_status') != 'complete' or bool(trajectory))
        and (measured.get('trajectory_status') == 'complete' or not measured.get('trajectory'))
        and MIN_MEASURED_CONFIDENCE <= confidence <= 1
        and finite_number(measured.get('valid_pair_count')) >= 2
        and finite_number(measured.get('scale_change_percent'), -100) > -100
        and all(isfinite(finite_number(measured.get(key), float('nan'))) for key in (
            'scale_change_percent', 'translation_x_ratio', 'translation_y_ratio', 'rotation_deg'))
        and all(isfinite(finite_number(measured.get(key)) * 100) for key in (
            'translation_x_ratio', 'translation_y_ratio'))
    )


def build_animation_plan(shot: dict, transform: dict, measured: bool,
                         trajectory: list[MotionSample], channels: dict) -> dict:
    source = 'measured' if measured else 'semantic' if transform else 'insufficient'
    timing = shot.get('time') or {}
    start = finite_number(timing.get('start'), float('nan'))
    end = finite_number(timing.get('end'), float('nan'))
    valid_time = isfinite(start) and isfinite(end) and 0 <= start < end
    duration = end - start if valid_time else None
    evidence = shot.get('measured_motion') or {}
    coverage_valid = bool(trajectory and valid_time and trajectory[0].source_time >= start
                          and trajectory[-1].source_time < end)
    curves = curves_from_channels(channels, start) if coverage_valid else []
    notes = []
    if measured:
        notes.append('参数来自有效采样帧对的变换估计；只是复现起点，并非原工程参数。')
        if not transform and (not trajectory or coverage_valid):
            notes.append('可靠测量未达到变换阈值，建议先保持静止，不添加推近或平移关键帧。')
        if not trajectory:
            notes.append('旧端点数据只描述首尾净变化，不能排除中途往返运动；静止仅为试作起点。')
            if evidence.get('translation_reference', 'legacy_top_left') == 'legacy_top_left':
                notes.append('旧版平移以画面左上角为参考；与缩放或旋转同时发生时，不能直接作为中心锚点 Position 的位移。')
    elif transform:
        notes.append('运动测量不可用或置信度不足，以下幅度是依据 AI 方向判断给出的试作值，未被视频测量验证。')
    else:
        notes.append('缺少可靠运动证据，不生成数值关键帧；可先检查原片或重新分析。')
    if evidence.get('status') == 'localized_support':
        notes.append('跟踪点集中在画面局部。请在原片中选取相距较远的背景细节核对；若仅图层在移动，可在 AE 中单独跟踪该图层。')
    elif evidence.get('status') == 'mixed_support':
        notes.append('画面中有多组运动。请对照背景与前景分别选取跟踪点，核对哪个图层需要动画。')
    elif evidence.get('status') == 'incomplete_tracking' or evidence.get('trajectory_status') == 'partial':
        notes.append('跟踪未覆盖整个镜头。请按连续跟踪段核对位移，在缺口前后分别设置参考帧。')
    if (shot.get('motion_summary') or {}).get('conflict'):
        notes.append('AI 运动判断与画面测量存在分歧，请先逐帧核对。' +
                     ('这里优先采用可靠测量。' if measured else '当前建议仅为语义试作值。'))
    if transform:
        if 'position_x' in transform or 'position_y' in transform:
            if measured:
                notes.append('位移以画面宽或高的百分比表示。乘以对应合成尺寸再除以 100，将所得像素偏移加到起始 Position。')
            else:
                notes.append('位移试作值以像素表示。将水平偏移加到起始 Position X，或将垂直偏移加到起始 Position Y。')
        notes.extend([
            'AE 前提：无父层二维预合成，尺寸与源画面一致，中心锚点、起始缩放100%、旋转0；其他图层需先转换坐标。',
            '先使用时间线性插值，Position 同时设为空间线性插值，再对照原片调整缓动；尚未测量连续速度曲线，无法还原 Easy Ease 或贝塞尔参数。',
        ])
        if coverage_valid:
            notes.append('曲线保留实际采样时间，按各属性容差简化；容差只约束采样点重建误差，不代表跟踪误差。')
            notes.append('未将首尾外推到镜头边界；采样之间可能遗漏高速变化。起止值相同也可能包含往返运动。')
        elif not trajectory:
            notes.append('关键帧时间为试作安排：局部0秒到镜头末端；这些时间没有实际采样依据。')
    if trajectory and not coverage_valid:
        notes.append('轨迹采样时间超出镜头范围，不发布时间曲线或端点关键帧，请重新分析。')
    if not valid_time:
        notes.append('镜头时间缺失或无效，保留参数参考，不生成带时间的关键帧。')
    keyframes = [
        {'property': key, 'unit': value['unit'], 'basis': value['basis'],
         'start_time': 0.0, 'end_time': duration,
         'from': value['from'], 'to': value['to']}
        for key, value in transform.items()
    ] if valid_time and not trajectory else [
        {'property': curve['property'], 'unit': curve['unit'], 'basis': curve['basis'],
         'start_time': curve['points'][0]['time'], 'end_time': curve['points'][-1]['time'],
         'from': curve['points'][0]['value'], 'to': curve['points'][-1]['value']}
        for curve in curves
    ]
    plan = {
        'evidence_source': source,
        'source_start': start if valid_time else None,
        'source_end': end if valid_time else None,
        'duration': duration,
        'time_origin': '镜头局部秒；0 秒对应源视频 source_start',
        'coverage_start': trajectory[0].source_time if coverage_valid else None,
        'coverage_end': trajectory[-1].source_time if coverage_valid else None,
        'keyframes': keyframes,
        'curves': curves,
        'notes': notes,
    }
    if measured and coverage_valid:
        pairs = evidence.get('pairs') or []
        if not pairs or any(not isinstance(pair, dict) or pair.get('support_area_ratio') is None for pair in pairs):
            plan['evidence_notice'] = LEGACY_SPATIAL_NOTICE
        padding = artwork_padding(trajectory, start, curves, evidence.get('frame_width'), evidence.get('frame_height'))
        if padding is not None:
            plan['artwork_padding'] = padding
            notes.append('素材留边覆盖导出的 AE 线性曲线在关键帧之间的连续变换；原片在采样之间的实际运动仍需核对。')
    return plan

