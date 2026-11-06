"""Readable exports retain intermediate animation points, including reversals."""
from math import isfinite


def _cell(value):
    return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return f'{value:.6f}'.rstrip('0').rstrip('.') or '0'
    return '未知'


def _artwork_padding_lines(value) -> list[str]:
    if not isinstance(value, dict):
        return []
    keys = ('left_px', 'right_px', 'top_px', 'bottom_px', 'width_px', 'height_px')
    sizes = [value.get(key) for key in keys]
    if not all(type(n) in (int, float) and 0 <= n <= 30000 and n == int(n) for n in sizes):
        return []
    left, right, top, bottom, width, height = map(int, sizes)
    original_width, original_height = width - left - right, height - top - bottom
    if min(original_width, original_height) < 4 or not any((left, right, top, bottom)):
        return []
    anchor = f'({left + original_width / 2:g}, {top + original_height / 2:g})'
    return ['', '**素材留边建议**', '',
            f'- 按实测帧估算，左补 {left}、右补 {right}、上补 {top}、下补 {bottom} 像素。请回看帧间运动，检查是否露边。',
            '- 留边脚本已设置 CONTENT 尺寸和锚点。请用下述尺寸的静态图稿替换，并将原画面对齐到留边位置。',
            f'- 手动修改原尺寸模板时，CONTENT 预合成会裁掉画布外的素材。将素材和 CONTENT 都扩到 {width} × {height} 像素，'
            f'在新边缘补足画面，并将原画面的左上角放在 ({left}, {top})。',
            f'- 在外层 MOTION 合成中选中 CONTENT 图层，把锚点（Anchor Point）设为 {anchor}，'
            '对齐原画面中心。保留已有的位置（Position）和缩放（Scale）关键帧。']


def animation_plan_markdown(plan: dict) -> list[str]:
    """Keep the detailed curve alongside legacy endpoint-only recipes."""
    if not isinstance(plan, dict) or not plan:
        return []
    labels = {'position_x': '水平位移', 'position_y': '垂直位移',
              'global_scale': '缩放', 'rotation': '旋转'}
    lines = ['- 关键帧时间：镜头局部秒；0 秒对应源视频镜头入点。']
    if plan.get('evidence_notice'):
        lines.append(f"- {_cell(plan['evidence_notice'])}")
    if plan.get('coverage_start') is not None:
        lines.append(f"- 实测覆盖：源视频 {_number(plan.get('coverage_start'))}–"
                     f"{_number(plan.get('coverage_end'))} 秒；未外推到镜头边界。")
    curves = plan.get('curves') or []
    if curves:
        for curve in curves:
            name = labels.get(curve.get('property'), curve.get('property', '未知属性'))
            lines.extend(['', f"**{_cell(name)}** · {_cell(curve.get('unit', ''))}", '',
                          f"线性插值；采样重建容差 {_number(curve.get('tolerance'))} {_cell(curve.get('unit', ''))}。",
                          '', '| 局部时间（秒） | 值 |', '| ---: | ---: |'])
            lines.extend(f"| {_number(p.get('time'))} | {_number(p.get('value'))} |"
                         for p in curve.get('points', []))
    else:
        for item in plan.get('keyframes') or []:
            name = labels.get(item.get('property'), item.get('property', '未知属性'))
            lines.append(f"- {_cell(name)}：{_number(item.get('start_time'))}s 的 {_number(item.get('from'))} → "
                         f"{_number(item.get('end_time'))}s 的 {_number(item.get('to'))} "
                         f"{_cell(item.get('unit', ''))}（{_cell(item.get('basis', ''))}）")
    if curves and plan.get('evidence_source') == 'measured':
        lines.extend(_artwork_padding_lines(plan.get('artwork_padding')))
    lines.extend(f'- {_cell(note)}' for note in plan.get('notes') or [])
    return lines
