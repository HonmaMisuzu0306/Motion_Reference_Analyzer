from recipe.ae_recipe import generate_ae_recipe
from recipe.report import animation_plan_markdown
from selection.export import export_selection
from tests.test_motion_curves import measured_shot


def test_markdown_preserves_middle_of_roundtrip():
    shot = measured_shot([0, .1, 0], [12.1, 12.5, 13.5])
    plan = generate_ae_recipe(shot)['animation_plan']
    report = '\n'.join(animation_plan_markdown(plan))
    assert '| 0.5 | 10 |' in report
    assert '| 0.1 | 0 |' in report and '| 1.5 | 0 |' in report
    assert '12.1–13.5' in report and '采样重建容差 0.1' in report


def test_selection_markdown_contains_readable_curves(tmp_path):
    shot = measured_shot([0, .1, 0], [12.1, 12.5, 13.5])
    shot['ae_recipe'] = generate_ae_recipe(shot)
    record = {'id': 'roundtrip', 'status': 'done', 'kind': 'clip', 'source_hash': 'hash',
              'result': {'time': shot['time'], 'shots': [shot]}}
    report = export_selection(record, 'markdown', tmp_path).read_text(encoding='utf-8')
    assert '**水平位移**' in report and '| 0.5 | 10 |' in report


def test_legacy_endpoint_report_remains_readable():
    text = '\n'.join(animation_plan_markdown({'keyframes': [{
        'property': 'position_x', 'start_time': 0, 'end_time': 2,
        'from': 0, 'to': 8, 'unit': '% frame width', 'basis': 'semantic'}]}))
    assert '0s 的 0 → 2s 的 8' in text


def test_padding_report_repositions_anchor_in_asymmetrically_expanded_artwork():
    plan = {'evidence_source': 'measured', 'curves': [{'property': 'position_x'}]}
    padding = {'left_px': 41, 'right_px': 7, 'top_px': 0, 'bottom_px': 18, 'width_px': 369, 'height_px': 198}
    def report(value):
        return '\n'.join(animation_plan_markdown({**plan, 'artwork_padding': value}))
    assert '369 × 198' in report(padding)
    assert 'Anchor Point）设为 (201.5, 90)' in report(padding)
    assert '左上角放在 (41, 0)' in report(padding)
    for invalid in (None, {}, {**padding, 'width_px': True}, {**padding, 'height_px': 18},
                    {**padding, 'top_px': .5}, {**padding, 'width_px': 30001}):
        assert '素材留边建议' not in report(invalid)


def test_selection_markdown_explains_missing_total_before_raw_result(tmp_path):
    shot = {'shot_id': 'patch', 'measured_motion': {'status': 'localized_support',
            'message': '跟踪点集中在画面局部', 'translation_x_ratio': 0.0}}
    record = {'id': 'local', 'status': 'done', 'kind': 'clip', 'source_hash': 'hash',
              'result': {'time': {'start': 2, 'end': 3}, 'shots': [shot]}}
    report = export_selection(record, 'markdown', tmp_path).read_text(encoding='utf8')
    readable = report.split('## 分析结果与复现建议')[0]
    assert '整镜头运动测量不可用：跟踪点集中在画面局部' in readable
