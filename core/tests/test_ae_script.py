import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.main import app
from recipe import ae_script
from recipe.ae_script import build_ae_setup, export_ae_script
from schemas import Project, Shot, VideoInfo
from tests.test_motion_curves import measured_shot


def test_jsx_executes_with_exact_local_times_and_pixel_conversion(tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the ExtendScript contract test')
    shot = measured_shot([0, .1, 0], [12.1, 12.5, 13.5])
    # Input text must remain literal data, never run as a second script.
    shot['shot_id'] = '测试 "; throw new Error("injected"); //\n\u2028'
    path = export_ae_script(shot, width=100, height=100, fps=24, path=tmp_path / 'prototype.jsx')
    output = subprocess.run([node, str(Path(__file__).parent / 'fixtures/ae_mock.cjs'), str(path)],
                            capture_output=True, text=True, encoding='utf-8', check=True, timeout=5)
    state = json.loads(output.stdout)
    assert state['alerts'] == []
    assert state['undoStart'] == state['undoEnd'] == 1
    assert len(state['comps']) == 2 and len(state['folders']) == 1
    comp = state['comps'][1]
    assert shot['shot_id'] in comp['name']
    assert comp['duration'] == 2 and comp['fps'] == 24
    layer = comp['entries'][0]
    assert layer['props']['ADBE Anchor Point']['value'] == [50, 50]
    position = layer['props']['ADBE Position']
    assert position['dimensionsSeparated'] is True
    keys = position['followers']['0']['keys']
    assert [key['time'] for key in keys] == pytest.approx([.1, .5, 1.5])
    assert [key['value'] for key in keys] == [50, 60, 50]
    assert all(key['interpolation'] == ['linear', 'linear'] for key in keys)
    assert comp['workAreaStart'] == pytest.approx(.1)
    assert comp['workAreaDuration'] == pytest.approx(1.4 + 1 / 24)
    assert 'not measured evidence' in comp['comment']


def test_all_axes_use_their_own_units_and_frame_dimensions(tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the ExtendScript contract test')
    shot = measured_shot([0, .05, .1], [12.1, 12.5, 13.5])
    measured = shot['measured_motion']
    measured.update(frame_width=200, translation_x_px=20, translation_y_px=12,
                    translation_y_ratio=.12, scale_ratio=1.1, scale_change_percent=10, rotation_deg=20)
    for i, sample in enumerate(measured['trajectory']):
        scale, angle, dx, dy = 1 + .05 * i, math.radians(10 * i), 10 * i, 6 * i
        a, b = scale * math.cos(angle), scale * math.sin(angle)
        sample.update(translation_x_px=dx, translation_y_px=dy, translation_y_ratio=dy / 100,
                      scale_ratio=scale, rotation_deg=10 * i,
                      matrix=((a, -b, 100 + dx - a * 100 + b * 50),
                              (b, a, 50 + dy - b * 100 - a * 50)))
    path = export_ae_script(shot, width=200, height=100, fps=24, path=tmp_path / 'all-axes.jsx')
    output = subprocess.run([node, str(Path(__file__).parent / 'fixtures/ae_mock.cjs'), str(path)],
                            capture_output=True, text=True, encoding='utf-8', check=True, timeout=5)
    state = json.loads(output.stdout)
    assert state['alerts'] == []
    props = state['comps'][1]['entries'][0]['props']
    followers = props['ADBE Position']['followers']
    assert [p['value'] for p in followers['0']['keys']] == [100, 110, 120]
    assert [p['value'] for p in followers['1']['keys']] == [50, 56, 62]
    assert [p['value'][0] for p in props['ADBE Scale']['keys']] == pytest.approx([100, 105, 110])
    assert all(p['value'][0] == p['value'][1] for p in props['ADBE Scale']['keys'])
    assert [p['value'] for p in props['ADBE Rotate Z']['keys']] == [0, 10, 20]


@pytest.mark.parametrize('mutate', ['semantic', 'partial', 'static', 'bad_time', 'bad_size'])
def test_unqualified_data_never_creates_a_script(tmp_path, mutate):
    shot = measured_shot([0, .1, 0], [12.1, 12.5, 13.5])
    measured = shot['measured_motion']
    if mutate == 'semantic':
        measured['confidence'] = .1
        shot['motion'] = {'type': 'push_in', 'confidence': .9}
    elif mutate == 'partial':
        measured['trajectory_status'] = 'partial'
    elif mutate == 'static':
        shot = measured_shot([0, 0, 0], [12.1, 12.5, 13.5])
    elif mutate == 'bad_time':
        shot['time']['end'] = 12.4
    else:
        measured['frame_width'] = 200
    path = tmp_path / 'export/prototype.jsx'
    with pytest.raises(ValueError):
        export_ae_script(shot, width=100, height=100, fps=24, path=path)
    assert not path.parent.exists()


@pytest.mark.parametrize('fps', [0, 1000, float('nan'), float('inf'), True, 10 ** 1000])
def test_invalid_comp_fps_is_rejected(fps):
    with pytest.raises(ValueError):
        build_ae_setup(measured_shot([0, .1, 0], [12.1, 12.5, 13.5]), width=100, height=100, fps=fps)


def test_export_endpoint_supports_saved_evidence_without_source_media(tmp_path, monkeypatch):
    shot = measured_shot([0, .1, 0], [12.1, 12.5, 13.5])
    project = Project(shots=[Shot.model_validate(shot)], video_path='missing.mp4',
                      video=VideoInfo(filename='missing.mp4', duration=14, width=100, height=100,
                                      fps=24, codec='h264'))
    monkeypatch.setattr(api, '_project_state', project)
    monkeypatch.setattr(api, 'OUTPUT_DIR', tmp_path)
    client = TestClient(app)
    response = client.post('/api/v1/shots/test/export/ae')
    assert response.status_code == 200, response.text
    assert Path(response.json()['path']).is_file()
    assert client.post('/api/v1/shots/missing/export/ae').status_code == 404
    project.shots[0].measured_motion.confidence = .1
    assert client.post('/api/v1/shots/test/export/ae').status_code == 409


def _execute_script(path, max_fps=999):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the ExtendScript contract test')
    output = subprocess.run([node, str(Path(__file__).parent / 'fixtures/ae_mock.cjs'), str(path), str(max_fps)],
                            capture_output=True, text=True, encoding='utf-8', check=True, timeout=5)
    return json.loads(output.stdout)


def test_cached_recipe_cannot_replace_validated_motion_or_execute_text(tmp_path):
    shot = measured_shot([0, -.1, -.2], [12.1, 12.5, 13.5])
    shot['ae_recipe'] = {
        'animation_plan': {'evidence_source': 'measured',
                           'curves': [{'property': 'position_x', 'points': [{'time': 0, 'value': float('nan')}]}]},
        'name': '"; throw new Error("cached recipe executed"); //',
    }
    path = export_ae_script(shot, width=100, height=100, fps=24, path=tmp_path / 'fresh-evidence.jsx')
    state = _execute_script(path)
    assert state['alerts'] == []
    keys = state['comps'][1]['entries'][0]['props']['ADBE Position']['followers']['0']['keys']
    assert [key['value'] for key in keys] == [50, 40, 30]
    assert 'cached recipe executed' not in path.read_text(encoding='utf-8')


def test_forged_cached_recipe_does_not_enable_legacy_endpoint_export(tmp_path):
    shot = measured_shot([0, .1, .2], [12.1, 12.5, 13.5])
    shot['ae_recipe'] = {'animation_plan': build_ae_setup(shot, width=100, height=100, fps=24)}
    shot['measured_motion'].update(trajectory=[], trajectory_status='not_measured')
    path = tmp_path / 'blocked/prototype.jsx'
    with pytest.raises(ValueError, match='实测轨迹'):
        export_ae_script(shot, width=100, height=100, fps=24, path=path)
    assert not path.parent.exists()


def test_large_finite_offsets_do_not_overflow_during_pixel_conversion(tmp_path):
    shot = measured_shot([0, 1e306, 0], [12.1, 12.5, 13.5])
    path = export_ae_script(shot, width=100, height=100, fps=24, path=tmp_path / 'finite.jsx')
    state = _execute_script(path)
    assert state['alerts'] == []
    keys = state['comps'][1]['entries'][0]['props']['ADBE Position']['followers']['0']['keys']
    assert math.isfinite(keys[1]['value'])
    assert keys[1]['value'] == pytest.approx(1e308)


def test_nonfinite_converted_values_are_rejected_before_creating_files(tmp_path, monkeypatch):
    shot = measured_shot([0, .1, 0], [12.1, 12.5, 13.5])
    shot['measured_motion']['frame_width'] = 10000
    monkeypatch.setattr(ae_script, 'generate_ae_recipe', lambda _: {'animation_plan': {
        'evidence_source': 'measured', 'duration': 2,
        'curves': [{'property': 'position_x', 'points': [{'time': 0, 'value': 0}, {'time': 1, 'value': 1e308}]}],
    }})
    path = tmp_path / 'blocked/overflow.jsx'
    with pytest.raises(ValueError, match='有限数值'):
        export_ae_script(shot, width=10000, height=100, fps=24, path=path)
    assert not path.parent.exists()


def test_odd_dimensions_use_exact_center_and_preview_includes_final_frame(tmp_path):
    shot = measured_shot([0, .1, .2], [12.1, 12.51, 13.99])
    measured = shot['measured_motion']
    measured.update(frame_width=101, frame_height=99, translation_x_px=20.2)
    for sample in measured['trajectory']:
        dx = sample['translation_x_ratio'] * 101
        sample.update(translation_x_px=dx, matrix=((1, 0, dx), (0, 1, 0)))
    path = export_ae_script(shot, width=101, height=99, fps=29.97, path=tmp_path / 'odd-size.jsx')
    state = _execute_script(path)
    assert state['alerts'] == []
    comp = state['comps'][1]
    props = comp['entries'][0]['props']
    assert props['ADBE Anchor Point']['value'] == [50.5, 49.5]
    assert props['ADBE Position']['value'] == [50.5, 49.5]
    assert comp['workAreaStart'] == pytest.approx(.1)
    assert comp['workAreaStart'] + comp['workAreaDuration'] == pytest.approx(2)
    keys = props['ADBE Position']['followers']['0']['keys']
    assert [key['time'] for key in keys] == pytest.approx([.1, .51, 1.99])
    assert [key['value'] for key in keys] == pytest.approx([50.5, 60.6, 70.7])


@pytest.mark.parametrize('width,height', [(True, 100), (100, False), (0, 100), (100, 30001), (100.0, 100)])
def test_invalid_comp_dimensions_are_rejected(width, height):
    with pytest.raises(ValueError, match='合成尺寸'):
        build_ae_setup(measured_shot([0, .1, 0], [12.1, 12.5, 13.5]), width=width, height=height, fps=24)


@pytest.mark.parametrize('source_fps,host_limit,preview_fps', [
    (120, 999, 120), (240, 999, 240), (120000 / 1001, 99, 60000 / 1001), (240, 99, 80),
])
def test_high_frame_rate_preserves_seconds_on_modern_and_legacy_hosts(tmp_path, source_fps, host_limit, preview_fps):
    shot = measured_shot([0, .1, 0], [12, 12.25, 12.5])
    path = export_ae_script(shot, width=100, height=100, fps=source_fps, path=tmp_path / 'high-fps.jsx')
    state = _execute_script(path, host_limit)
    assert state['alerts'] == []
    assert [comp['fps'] for comp in state['comps']] == pytest.approx([preview_fps] * 2)
    comp = state['comps'][1]
    assert comp['workAreaDuration'] == pytest.approx(.5 + 1 / preview_fps)
    assert ('this AE host previews at' in comp['comment']) == (source_fps > host_limit)
    keys = comp['entries'][0]['props']['ADBE Position']['followers']['0']['keys']
    assert [key['time'] for key in keys] == [0, .25, .5]
    assert [key['value'] for key in keys] == [50, 60, 50]


def test_padded_comp_preserves_marker_positions_and_outer_dimensions(tmp_path):
    shot = measured_shot([0, .10, 0], [12.1, 12.5, 13.5])
    path = export_ae_script(shot, width=100, height=100, fps=24, padded=True,
                            path=tmp_path / 'padded.jsx')
    mock = Path(__file__).parent / 'fixtures/ae_mock.cjs'
    state = json.loads(subprocess.check_output(['node', str(mock), str(path)], timeout=5))
    assert not state['alerts']
    content, comp = state['comps']
    assert (content['width'], content['height']) == (110, 100)
    assert (comp['width'], comp['height']) == (100, 100)
    props = comp['entries'][0]['props']
    assert props['ADBE Anchor Point']['value'] == [60, 50]
    assert content['entries'][0]['props']['ADBE Position']['value'] == [45, 50]
    assert [key['value'] for key in props['ADBE Position']['followers']['0']['keys']] == [50, 60, 50]
