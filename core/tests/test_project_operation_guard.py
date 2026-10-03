"""Project mutations must not replace state beneath an in-flight analysis/load."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import api
from app.config import reset_config
from app.main import app
from schemas import Project, Shot, TimeRange, VideoInfo

SAMPLE = Path(__file__).resolve().parents[2] / 'samples/test_typography.mp4'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUTO_SAVE_TO_LIBRARY', 'false')
    reset_config()
    with TestClient(app) as value:
        yield value


def saved_project(tmp_path):
    source = tmp_path / 'other.mp4'
    source.write_bytes(b'other source')
    return api._get_library().save_analysis(Project(project_name='other', video_path=str(source),
        assets_dir=str(tmp_path / 'other-assets'),
        video=VideoInfo(filename='other.mp4', duration=1, width=100, height=100, fps=24, codec='h264'),
        shots=[Shot(shot_id='other_shot', time=TimeRange(start=0, end=1, duration=1))]))


def test_running_analysis_rejects_load_import_and_save_without_state_changes(client, tmp_path, monkeypatch):
    project_id = saved_project(tmp_path)
    assert client.post('/api/v1/video/import', json={'path': str(SAMPLE)}).status_code == 200
    entered = Event()
    release = Event()

    def blocked_detection(path):
        entered.set()
        assert release.wait(5)
        return [{'shot_id': 'shot_001', 'start': 0, 'end': 1, 'duration': 1}]

    monkeypatch.setattr(api, 'detect_scenes', blocked_detection)
    with ThreadPoolExecutor(1) as worker:
        analysis = worker.submit(client.post, '/api/v1/video/analyze')
        try:
            assert entered.wait(5)
            running = api._project_state
            before = running.model_dump()
            responses = [client.post(f'/api/v1/library/projects/{project_id}/load'),
                         client.post('/api/v1/video/import', json={'path': str(tmp_path / 'missing.mp4')}),
                         client.post('/api/v1/library/save')]
            assert [response.status_code for response in responses] == [409, 409, 409]
            assert api._project_state is running
            assert api._project_state.model_dump() == before
        finally:
            release.set()
        result = analysis.result(timeout=10)
    assert result.status_code == 200, result.text
    status = client.get('/api/v1/project/status').json()
    assert status['status'] in {'done', 'completed_with_warnings'}
    assert status['video_path'] == str(SAMPLE)
    assert status['shot_count'] == 1
    assert client.post('/api/v1/library/save').status_code == 200


def test_loading_project_rejects_analysis_before_it_can_mutate_idle_state(client, tmp_path, monkeypatch):
    project_id = saved_project(tmp_path)
    lib = api._get_library()
    actual_load = lib.load_project
    entered = Event()
    release = Event()

    def blocked_load(pid):
        entered.set()
        assert release.wait(5)
        return actual_load(pid)

    monkeypatch.setattr(lib, 'load_project', blocked_load)
    with ThreadPoolExecutor(1) as worker:
        loading = worker.submit(client.post, f'/api/v1/library/projects/{project_id}/load')
        try:
            assert entered.wait(5)
            before = api._project_state.model_dump()
            assert client.post('/api/v1/video/analyze').status_code == 409
            assert api._project_state.model_dump() == before
        finally:
            release.set()
        assert loading.result(timeout=5).status_code == 200
    assert api._project_state.project_name == 'other'


def test_failed_operation_releases_guard_for_next_import(client, tmp_path):
    assert client.post('/api/v1/video/import', json={'path': str(tmp_path / 'missing.mp4')}).status_code == 404
    assert client.post('/api/v1/video/import', json={'path': str(SAMPLE)}).status_code == 200
