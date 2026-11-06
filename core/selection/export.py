import json
from pathlib import Path
from typing import Literal

from recipe.ae_recipe import has_global_totals
from recipe.report import animation_plan_markdown
from selection.blend_color import color_advice


def export_selection(record: dict, format: Literal['json', 'markdown'], directory: Path) -> Path:
    if format not in ('json', 'markdown'):
        raise ValueError('导出格式无效')
    if record['status'] not in ('done', 'completed_with_warnings'):
        raise ValueError('仅能导出已完成的记录')
    directory.mkdir(parents=True, exist_ok=True)
    # Database IDs are never interpreted as a caller-supplied filesystem path.
    import hashlib

    filename = hashlib.sha256(record['id'].encode()).hexdigest()[:20]
    path = directory / f"MRA-{record['kind']}-{filename}.{'json' if format == 'json' else 'md'}"
    data = {'schema_version': 1, **{key: record.get(key) for key in
            ('id', 'kind', 'source_hash', 'request', 'status', 'result', 'versions', 'warnings', 'created_at')}}
    if format == 'json':
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    else:
        result, time = record['result'], record['result'].get('time', {})
        lines = ['# MRA 局部分析', '', f"- 类型：{'单帧' if record['kind'] == 'frame' else '片段'}",
                 f"- 源视频 SHA256：{record['source_hash']}"]
        if record['kind'] == 'frame':
            lines.extend([f"- 实际源时间：{time.get('actual_time', 0):.3f} 秒；PTS：{time.get('pts', '')}",
                          '- 能力限制：仅静态构图、文字、色彩与效果；运动、转场、动画和节奏不适用'])
        else:
            lines.append(f"- 源范围：[{time.get('start', 0):.3f}, {time.get('end', 0):.3f}) 秒")
            if result.get('measurement') == 'opacity_blend':
                if result.get('measurement_message'):
                    lines.extend(['', result['measurement_message']])
            else:
                lines.append('- 范围采用半开区间；入点不是切镜；短于8秒不估计BPM')
            blend = result.get('opacity_blend')
            if blend:
                lines.extend(['', '## 叠化 · AE 顶层不透明度', '',
                              f"按 {blend['sample_count']} 帧的画面混合比例估算。将选区入点对齐到合成零秒，"
                              '起始画面放在底层并保持 100%，结束画面放在顶层，按表设置线性关键帧。', '', color_advice(blend), '',
                              '| 源时间（秒） | 合成时间（秒） | 顶层不透明度 |', '| ---: | ---: | ---: |'])
                for key in blend['keyframes']:
                    source = key['source_time']
                    lines.append(f"| {source:.3f} | {source - time['start']:.3f} | {key['opacity_percent']:.1f}% |")
            for shot in result.get('shots', []):
                lines.extend(['', f"## {shot.get('shot_id', '镜头')} · AE 动画建议", ''])
                measured = shot.get('measured_motion') or {}
                if measured and not has_global_totals(measured.get('status'), measured.get('trajectory_status'),
                                                      measured.get('valid_pair_count')):
                    lines.append('- 整镜头运动测量不可用：' + (measured.get('message') or '请检查有效帧对和连续跟踪段。'))
                lines.extend(animation_plan_markdown((shot.get('ae_recipe') or {}).get('animation_plan', {})))
        lines.extend(['', '## 警告', '', *[f'- {w}' for w in record.get('warnings', [])],
                      '', '## 分析结果与复现建议', '', '```json',
                      json.dumps(result, ensure_ascii=False, indent=2), '```',
                      '', '## 模型与版本', '', '```json',
                      json.dumps(record.get('versions', {}), ensure_ascii=False, indent=2), '```'])
        content = '\n'.join(lines)
    path.write_text(content, encoding='utf-8')
    return path
