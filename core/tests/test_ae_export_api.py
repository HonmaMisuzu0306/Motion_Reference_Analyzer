"""AE export routes read saved evidence without changing working or archived analysis."""
import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.main import app
from db.connection import get_db_path
from schemas import Project, Shot, VideoInfo
from selection.store import SelectionStore
from tests.test_motion_curves import measured_shot


@pytest.fixture
def client():
    # The autouse isolated_library fixture supplies a real temporary SQLite file.
    with TestClient(app) as value:
        yield value


def save_project(tmp_path, name='first', *, width=100, start=12, values=(0, .1, .2), invalid=None):
    shot = measured_shot(values, [start + .1, start + .5, start + 1.5], start=start, end=start + 2)
    shot['shot_id'] = 'shared_shot'
    shot['ae_recipe'] = {'version': 'old-cache', 'notes': name, 'transform': {'position_x': {'to': 99999}}}
    measured = shot['measured_motion']
    measured.update(frame_width=width, translation_x_px=values[-1] * width)
    for point in measured['trajectory']:
        dx = point['translation_x_ratio'] * width
        point.update(translation_x_px=dx, matrix=((1, 0, dx), (0, 1, 0)))
    if invalid == 'legacy':
        measured.update(trajectory_status='not_measured', trajectory=[])
    elif invalid == 'partial':
        measured.update(trajectory_status='partial', status='incomplete_tracking')
    source = tmp_path / f'{name}-missing.mp4'
    project = Project(
        project_name=name, video_path=str(source), analysis_status='done',
        video=VideoInfo(filename=source.name, duration=start + 2, width=width, height=100, fps=24, codec='h264'),
        shots=[Shot.model_validate(shot)],
    )
    library = api._get_library()
    pid = library.save_analysis(project)
    sid = library.list_shots(pid)[0].id
    assert get_db_path().is_file() and not source.exists()
    return pid, sid, shot


def save_selection(pid, shot, *, status='done', kind='clip'):
    store = SelectionStore(get_db_path())
    project = api._get_library().get_project(pid)
    rid = store.create(pid, kind, project.video_hash, {'kind': kind}, str(api.OUTPUT_DIR / 'selections'))
    result = {'kind': kind, 'time': shot['time'], 'shots': [shot]}
    if status == 'completed_with_warnings':
        result['partial_failures'] = ['Typography unavailable; measured motion is complete.']
    store.finish(rid, result, {'pipeline': 'fixture'}, [])
    if status not in ('done', 'completed_with_warnings'):
        # Persist a stale result with unfinished status to verify the status gate,
        # even when the record contains otherwise exportable motion evidence.
        with sqlite3.connect(get_db_path()) as connection:
            connection.execute('UPDATE selection_analyses SET status=? WHERE id=?', (status, rid))
    return rid


def load_working(client, pid):
    response = client.post(f'/api/v1/library/projects/{pid}/load')
    assert response.status_code == 200, response.text
    assert api._project_state.library_project_id == pid


def database_snapshot():
    with sqlite3.connect(get_db_path()) as connection:
        return tuple(connection.iterdump())


def export_snapshot():
    return api._project_state.model_dump(), database_snapshot(), set(api.OUTPUT_DIR.rglob('*.jsx'))


def assert_read_only(before, *, new_files=0):
    working, database, files = before
    assert api._project_state.model_dump() == working
    assert database_snapshot() == database
    current = set(api.OUTPUT_DIR.rglob('*.jsx'))
    assert files <= current and len(current - files) == new_files


def read_setup(response):
    assert response.status_code == 200, response.text
    path = Path(response.json()['path'])
    assert path.is_absolute() and path.suffix == '.jsx' and path.is_file()
    assert path.is_relative_to(api.OUTPUT_DIR.resolve())
    source = path.read_text(encoding='utf-8')
    assert 'app.beginUndoGroup' in source and 'setValueAtTime' in source
    match = re.search(r'    var data = (.+);\n', source)
    assert match is not None
    return path, json.loads(match.group(1))


def routes(sid, rid):
    return {
        'working': '/api/v1/shots/shared_shot/export/ae',
        'library': f'/api/v1/library/shots/{sid}/export/ae',
        'selection': f'/api/v1/selection-analyses/{rid}/shots/shared_shot/export/ae',
    }


@pytest.mark.parametrize('status', ['done', 'completed_with_warnings'])
def test_three_routes_export_saved_evidence_without_source_or_mutating_records(client, tmp_path, status):
    pid, sid, shot = save_project(tmp_path)
    rid = save_selection(pid, shot, status=status)
    load_working(client, pid)
    before = export_snapshot()
    paths = []
    for route in routes(sid, rid).values():
        path, setup = read_setup(client.post(route))
        paths.append(path)
        assert (setup['width'], setup['height'], setup['fps']) == (100, 100, 24)
        assert (setup['source_start'], setup['source_end']) == (12, 14)
        assert [p['value'] for p in setup['curves'][0]['points']] == [0, 10, 20]
        assert [p['time'] for p in setup['curves'][0]['points']] == pytest.approx([.1, .5, 1.5])
    assert len(set(paths)) == 3
    assert_read_only(before, new_files=3)


def test_identical_shot_ids_stay_bound_to_their_project_and_selection(client, tmp_path):
    first, first_sid, first_shot = save_project(tmp_path, 'first', width=100)
    second, second_sid, second_shot = save_project(tmp_path, 'second', width=200, start=20, values=(0, -.15, -.3))
    assert first != second and first_sid != second_sid
    first_rid = save_selection(first, first_shot)
    second_rid = save_selection(second, second_shot)
    load_working(client, second)
    before = export_snapshot()
    exported_paths = set()
    # The active project is deliberately different when reading the first archive.
    for route, width, start, endpoint in [
        (routes(second_sid, second_rid)['working'], 200, 20, -30),
        (routes(first_sid, first_rid)['library'], 100, 12, 20),
        (routes(first_sid, first_rid)['selection'], 100, 12, 20),
        (routes(second_sid, second_rid)['library'], 200, 20, -30),
        (routes(second_sid, second_rid)['selection'], 200, 20, -30),
    ]:
        path, setup = read_setup(client.post(route))
        exported_paths.add(path)
        assert (setup['width'], setup['source_start']) == (width, start)
        assert setup['curves'][0]['points'][-1]['value'] == endpoint
    assert len(exported_paths) == 5
    assert_read_only(before, new_files=5)
    load_working(client, first)
    before = export_snapshot()
    path, setup = read_setup(client.post(routes(first_sid, first_rid)['working']))
    assert path not in exported_paths
    assert (setup['width'], setup['source_start']) == (100, 12)
    assert_read_only(before, new_files=1)


@pytest.mark.parametrize('entrypoint', ['working', 'library', 'selection'])
@pytest.mark.parametrize('invalid', ['legacy', 'partial'])
def test_unqualified_saved_measurements_are_rejected_without_writes(client, tmp_path, entrypoint, invalid):
    pid, sid, shot = save_project(tmp_path, invalid=invalid)
    rid = save_selection(pid, shot)
    load_working(client, pid)
    before = export_snapshot()
    response = client.post(routes(sid, rid)[entrypoint])
    assert response.status_code == 409, response.text
    assert_read_only(before)


@pytest.mark.parametrize('status', ['preparing', 'running', 'error', 'interrupted'])
def test_unfinished_selection_cannot_export_even_with_saved_motion(client, tmp_path, status):
    pid, sid, shot = save_project(tmp_path)
    rid = save_selection(pid, shot, status=status)
    load_working(client, pid)
    before = export_snapshot()
    response = client.post(routes(sid, rid)['selection'])
    assert response.status_code == 409, response.text
    assert_read_only(before)


def test_single_frame_record_cannot_export_animation(client, tmp_path):
    pid, sid, shot = save_project(tmp_path)
    rid = save_selection(pid, shot, kind='frame')
    load_working(client, pid)
    before = export_snapshot()
    response = client.post(routes(sid, rid)['selection'])
    assert response.status_code == 409, response.text
    assert_read_only(before)


def test_busy_working_project_returns_conflict_without_writing(client, tmp_path):
    pid, sid, shot = save_project(tmp_path)
    rid = save_selection(pid, shot)
    load_working(client, pid)
    before = export_snapshot()
    assert api._project_operation_lock.acquire(blocking=False)
    try:
        response = client.post(routes(sid, rid)['working'])
        assert response.status_code == 409, response.text
        assert_read_only(before)
    finally:
        api._project_operation_lock.release()
    read_setup(client.post(routes(sid, rid)['working']))
    assert_read_only(before, new_files=1)


def test_missing_record_and_shot_ids_return_not_found_without_writes(client, tmp_path):
    pid, _, shot = save_project(tmp_path)
    rid = save_selection(pid, shot)
    load_working(client, pid)
    before = export_snapshot()
    for route in (
        '/api/v1/shots/missing/export/ae', '/api/v1/library/shots/999999/export/ae',
        '/api/v1/selection-analyses/missing/shots/shared_shot/export/ae',
        f'/api/v1/selection-analyses/{rid}/shots/missing/export/ae',
    ):
        response = client.post(route)
        assert response.status_code == 404, response.text
    assert_read_only(before)


def test_three_routes_can_export_padded_template(client, tmp_path):
    pid, sid, shot = save_project(tmp_path)
    rid = save_selection(pid, shot)
    load_working(client, pid)
    for route in routes(sid, rid).values():
        _, setup = read_setup(client.post(route, params={'padded': True}))
        assert setup['artwork_padding']['left_px'] == 20
        assert setup['width'] == 100


def test_archived_measurements_show_exportable_padding_without_resaving(client, tmp_path):
    pid, sid, shot = save_project(tmp_path)
    rid = save_selection(pid, shot)
    load_working(client, pid)
    before = export_snapshot()
    displayed = [
        client.get('/api/v1/shots').json()['shots'][0],
        client.get('/api/v1/shots/shared_shot').json(),
        client.get(f'/api/v1/library/shots/{sid}').json(),
        client.get(f'/api/v1/selection-analyses/{rid}').json()['result']['shots'][0],
    ]
    for item in displayed:
        recipe = item['ae_recipe']
        assert recipe['notes'] == 'first'
        assert recipe['animation_plan']['artwork_padding']['left_px'] == 20
        assert [p['value'] for p in recipe['animation_plan']['curves'][0]['points']] == [0, 10, 20]
    assert_read_only(before)
    archived = client.post(f'/api/v1/selection-analyses/{rid}/export', json={'format': 'json'})
    assert archived.status_code == 200
    raw = json.loads(Path(archived.json()['path']).read_text(encoding='utf-8'))
    assert raw['result']['shots'][0]['ae_recipe'] == shot['ae_recipe']


@pytest.mark.parametrize('invalid', ['partial', 'legacy'])
def test_archive_reads_do_not_infer_padding_from_unqualified_measurements(client, tmp_path, invalid):
    pid, sid, shot = save_project(tmp_path, invalid=invalid)
    rid = save_selection(pid, shot)
    load_working(client, pid)
    assert client.get('/api/v1/shots').json()['shots'][0]['ae_recipe'] == shot['ae_recipe']
    assert client.get(f'/api/v1/library/shots/{sid}').json()['ae_recipe'] == shot['ae_recipe']
    result = client.get(f'/api/v1/selection-analyses/{rid}').json()['result']
    assert result['shots'][0]['ae_recipe'] == shot['ae_recipe']


@pytest.mark.parametrize('reason', ['partial', 'dimension_mismatch', 'bad_matrix', 'no_curves'])
def test_v5_padding_is_hidden_without_valid_current_evidence(reason):
    from recipe.ae_recipe import shot_for_display

    values = [0, 0, 0] if reason == 'no_curves' else [0, .1, .2]
    shot = measured_shot(values, [12.1, 12.5, 13.5])
    cached = {'evidence_source': 'measured', 'artwork_padding': {'left_px': 1}, 'notes': ['saved']}
    shot['ae_recipe'] = {'version': 'ae-recipe-v5-artwork-padding', 'animation_plan': cached}
    if reason == 'partial':
        shot['measured_motion']['trajectory_status'] = 'partial'
    if reason == 'bad_matrix':
        shot['measured_motion']['trajectory'][1]['matrix'] = ((1, 0, 0), (0, 1, 0))
    width = 101 if reason == 'dimension_mismatch' else 100
    view = shot_for_display(shot, width, 100)
    assert 'artwork_padding' not in view['ae_recipe']['animation_plan']
    assert view['ae_recipe']['animation_plan']['notes'] == ['saved']
    assert shot['ae_recipe']['animation_plan']['artwork_padding'] == {'left_px': 1}


def test_old_global_curves_disclose_missing_spatial_support_in_views_scripts_and_reports(client, tmp_path):
    from recipe.keyframes import LEGACY_SPATIAL_NOTICE

    pid, sid, shot = save_project(tmp_path)
    rid = save_selection(pid, shot)
    load_working(client, pid)
    before = export_snapshot()

    plans = [
        client.get('/api/v1/shots/shared_shot').json()['ae_recipe']['animation_plan'],
        client.get(f'/api/v1/library/shots/{sid}/recipe').json()['animation_plan'],
        client.get(f'/api/v1/selection-analyses/{rid}').json()['result']['shots'][0]['ae_recipe']['animation_plan'],
    ]
    for plan in plans:
        assert plan['evidence_notice'] == LEGACY_SPATIAL_NOTICE
    assert_read_only(before)

    for route in routes(sid, rid).values():
        _, setup = read_setup(client.post(route, params={'padded': True}))
        assert setup['notes'].count(LEGACY_SPATIAL_NOTICE) == 1
        assert setup['artwork_padding']['left_px'] == 20
    assert_read_only(before, new_files=3)

    for response in [
        client.post('/api/v1/export/markdown'),
        client.post(f'/api/v1/library/shots/{sid}/export/recipe'),
        client.post(f'/api/v1/selection-analyses/{rid}/export', json={'format': 'markdown'}),
    ]:
        assert response.status_code == 200, response.text
        assert LEGACY_SPATIAL_NOTICE in Path(response.json()['path']).read_text(encoding='utf-8')
    stored = client.post(f'/api/v1/selection-analyses/{rid}/export', json={'format':'json'})
    archive = json.loads(Path(stored.json()['path']).read_text(encoding='utf-8'))
    assert archive['result']['shots'][0]['ae_recipe'] == shot['ae_recipe']
    assert_read_only(before, new_files=3)


def test_spatial_notice_uses_evidence_on_each_pair():
    from recipe.ae_recipe import generate_ae_recipe

    shot = measured_shot([0, .1, .2], [12, 12.5, 13])
    pairs = [{'start_time':start, 'end_time':start + .5, 'dx_px':10, 'valid':True, 'support_area_ratio':.6}
             for start in [12, 12.5]]
    shot['measured_motion']['pairs'] = pairs
    assert 'evidence_notice' not in generate_ae_recipe(shot)['animation_plan']
    pairs[1].pop('support_area_ratio')
    assert 'evidence_notice' in generate_ae_recipe(shot)['animation_plan']
