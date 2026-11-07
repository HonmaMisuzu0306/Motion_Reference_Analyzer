import time
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import api
from app.config import reset_config
from app.main import app
from selection import jobs
from tests.test_audio import write_av_video


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    reset_config()
    source = write_av_video(tmp_path / 'source.mp4', duration=2)
    with TestClient(app) as client:
        assert client.post('/api/v1/video/import', json={'path': str(source)}).status_code == 200
        pid = client.post('/api/v1/project/save').json()['project_id']
        yield client, pid, source


def wait_done(client, rid):
    for _ in range(200):
        record = client.get(f'/api/v1/selection-analyses/{rid}').json()
        if record['status'] not in ('preparing', 'running'):
            return record
        time.sleep(.02)
    raise AssertionError('job did not finish')


def test_bound_frame_and_clip_records_preserve_original_project(setup):
    client, pid, source = setup
    original = api._project_state.model_dump()
    position = client.get(f'/api/v1/projects/{pid}/frame-position?time=0.1').json()
    assert position['frame']['actual_time'] == pytest.approx(2 / 24)
    assert client.get(position['preview_url']).status_code == 200
    response = client.post(f'/api/v1/projects/{pid}/selection-analyses',
                           json={'kind': 'frame', 'frame': position['frame'], 'preview_token': position['preview_token']})
    assert response.status_code == 202, response.text
    record = wait_done(client, response.json()['record_id'])
    assert record['status'] == 'done', record
    assert client.get(f"/api/v1/selection-analyses/{record['id']}/assets/frame.png").status_code == 200
    assert api._project_state.model_dump() == original
    assert client.get(f'/api/v1/projects/{pid}/selection-analyses').json()['total'] == 1
    source.unlink()
    assert client.get(f"/api/v1/selection-analyses/{record['id']}").json()['source_available'] is False
    assert client.get(f"/api/v1/selection-analyses/{record['id']}/assets/frame.png").status_code == 200


def test_invalid_range_unbound_token_and_changed_source_do_not_create_record(setup):
    client, pid, source = setup
    route = f'/api/v1/projects/{pid}/selection-analyses'
    position = client.get(f'/api/v1/projects/{pid}/frame-position?time=0.1').json()
    assert client.post(route, json={'kind': 'clip', 'start': 1, 'end': 3}).status_code == 400
    assert client.post(route, json={'kind': 'frame', 'frame': position['frame'], 'preview_token': 'wrong'}).status_code == 409
    source.write_bytes(b'changed')
    assert client.post(route, json={'kind': 'clip', 'start': 0, 'end': 1}).status_code == 409
    assert client.get(f'/api/v1/projects/{pid}/selection-analyses').json()['total'] == 0


def test_worker_owns_lock_read_available_and_exception_releases(setup, monkeypatch):
    client, pid, _ = setup
    entered, release = Event(), Event()

    def blocked(snapshot, report):
        report('vision', 0, 1, '分析中')
        entered.set()
        assert release.wait(5)
        raise RuntimeError('provider failed')

    monkeypatch.setattr(jobs, 'run_selection', blocked)
    route = f'/api/v1/projects/{pid}/selection-analyses'
    try:
        submitted = client.post(route, json={'kind': 'clip', 'start': 0, 'end': 1})
        assert submitted.status_code == 202, submitted.text
        rid = submitted.json()['record_id']
        assert entered.wait(3)
        mutations = [client.post(route, json={'kind': 'clip', 'start': 0, 'end': 1}),
                     client.post('/api/v1/video/analyze'), client.post('/api/v1/video/analyze-audio'),
                     client.post('/api/v1/project/save'), client.post(f'/api/v1/library/projects/{pid}/load'),
                     client.put('/api/v1/settings', json=client.get('/api/v1/settings').json())]
        assert [r.status_code for r in mutations] == [409] * 6
        assert client.get(f'/api/v1/selection-analyses/{rid}').json()['status'] == 'running'
    finally:
        release.set()
    assert wait_done(client, rid)['status'] == 'error'
    assert client.post('/api/v1/project/save').status_code == 200


def test_source_changed_during_worker_is_not_published(setup, monkeypatch):
    client, pid, source = setup
    entered, release = Event(), Event()

    def blocked(snapshot, report):
        entered.set()
        assert release.wait(5)
        return {'versions': {}, 'warnings': [], 'kind': 'clip'}

    monkeypatch.setattr(jobs, 'run_selection', blocked)
    try:
        rid = client.post(f'/api/v1/projects/{pid}/selection-analyses', json={'kind': 'clip', 'start': 0, 'end': 1}).json()['record_id']
        assert entered.wait(3)
        source.write_bytes(b'changed during analysis')
    finally:
        release.set()
    record = wait_done(client, rid)
    assert record['status'] == 'error' and record['result'] == {}
    assert client.post('/api/v1/project/save').status_code == 409  # source identity conflict; lock released


def test_thread_start_failure_releases_lock_and_marks_record(setup, monkeypatch):
    client, pid, _ = setup

    class FailedThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError('thread start failed')

    monkeypatch.setattr(jobs, 'Thread', FailedThread)
    with pytest.raises(RuntimeError, match='thread start failed'):
        client.post(f'/api/v1/projects/{pid}/selection-analyses', json={'kind': 'clip', 'start': 0, 'end': 1})
    assert client.get(f'/api/v1/projects/{pid}/selection-analyses').json()['items'][0]['status'] == 'error'
    assert client.post('/api/v1/project/save').status_code == 200


def test_missing_models_and_cross_project_token_rejected_without_rows(setup):
    from app.config import get_config

    client, pid, _ = setup
    position = client.get(f'/api/v1/projects/{pid}/frame-position?time=0.1').json()
    forged = dict(position['frame'], pts=position['frame']['pts'] + 1)
    route = f'/api/v1/projects/{pid}/selection-analyses'
    assert client.post(route, json={'kind': 'frame', 'frame': forged, 'preview_token': position['preview_token']}).status_code == 409
    get_config().ocr_provider = 'paddleocr'
    get_config().ocr_models = []
    assert client.post(route, json={'kind': 'clip', 'start': 0, 'end': 1}).status_code == 409
    assert client.get(f'/api/v1/projects/{pid}/selection-analyses').json()['total'] == 0


def test_progress_polling_reuses_verified_source_and_detects_changes(setup, monkeypatch):
    from selection import api as selection_api
    client, pid, source = setup
    rid = selection_api._store().create(pid, 'clip', api._get_library().get_project(pid).video_hash,
                                       {'kind': 'clip', 'start': 0, 'end': 1}, str(source.parent / 'assets'))
    calls = []
    original = selection_api.video_hash
    def counting(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(selection_api, 'video_hash', counting)
    for _ in range(5):
        assert client.get(f'/api/v1/selection-analyses/{rid}').json()['source_available']
    assert len(calls) <= 1
    source.write_bytes(b'replaced')
    assert not client.get(f'/api/v1/selection-analyses/{rid}').json()['source_available']


def test_clip_geometry_survives_outdated_parent_dimensions(setup, monkeypatch):
    client, pid, _ = setup
    original = jobs.run_selection
    geometry_seen = []

    def observed(snapshot, report):
        geometry_seen.append(snapshot.display_geometry)
        return original(snapshot, report)

    monkeypatch.setattr(jobs, 'run_selection', observed)
    library = api._get_library()
    with library._conn:
        library._conn.execute('UPDATE projects SET video_width=120,video_height=160 WHERE id=?',(pid,))
    response = client.post(f'/api/v1/projects/{pid}/selection-analyses', json={'kind':'clip','start':0,'end':.5})
    assert response.status_code == 202, response.text
    record = wait_done(client,response.json()['record_id'])
    assert record['status'] in ('done','completed_with_warnings'), record
    assert geometry_seen == [(160,120,24.0)]
    assert record['result']['display_geometry'] == {'width':160,'height':120,'fps':24.0}
    assert library.get_project(pid).video_width == 120


def test_reanalysis_refreshes_legacy_project_display_size(setup):
    client, pid, _ = setup
    library = api._get_library()
    with library._conn:
        library._conn.execute('UPDATE projects SET video_width=120,video_height=160 WHERE id=?',(pid,))
    assert client.post(f'/api/v1/library/projects/{pid}/load').status_code == 200
    assert api._project_state.video.width == 120
    response = client.post('/api/v1/video/analyze', json={'mode':'basic'})
    assert response.status_code == 200, response.text
    saved = library.get_project(pid)
    assert (api._project_state.video.width,api._project_state.video.height) == (160,120)
    assert (saved.video_width,saved.video_height) == (160,120)
