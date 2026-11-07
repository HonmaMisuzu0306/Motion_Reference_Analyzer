"""A failed video import must leave the previous project usable."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import api
from app.main import app
from schemas import Shot, TimeRange
from tests.test_audio import write_wav
from tests.test_metadata import _create_test_video


@pytest.fixture
def current_project(tmp_path):
    client = TestClient(app, raise_server_exceptions=False)
    source = _create_test_video(tmp_path / 'original.mp4')
    assert client.post('/api/v1/video/import', json={'path': str(source)}).status_code == 200
    project = api._project_state
    project.display_name = '保留的项目'
    project.shots = [Shot(shot_id='shot_001', time=TimeRange(start=0, end=1, duration=1))]
    project.analysis_status = project.progress.status = 'done'
    project.progress.overall_progress = 1
    project.audio.status = 'no_audio'
    assert client.post('/api/v1/project/save').status_code == 200
    return client, project, project.model_dump()


@pytest.mark.parametrize('kind,status', [
    ('missing', 404), ('directory', 400), ('corrupt', 400), ('audio_only', 400),
])
def test_invalid_media_preserves_current_project(current_project, tmp_path, kind, status):
    client, project, before = current_project
    source = tmp_path / 'invalid.mp4'
    if kind == 'directory':
        source.mkdir()
    elif kind == 'corrupt':
        source.write_bytes(b'not a video')
    elif kind == 'audio_only':
        source = write_wav(tmp_path / 'audio.wav', np.zeros(22050, dtype=np.float32))

    response = client.post('/api/v1/video/import', json={'path': str(source)})
    assert response.status_code == status, response.text
    assert response.json()['detail']
    assert api._project_state is project
    assert project.model_dump() == before
    assert client.get('/api/v1/shots').json()['shots'][0]['shot_id'] == 'shot_001'
    # Failure also releases the operation guard, so the previous project can be saved.
    assert client.post('/api/v1/project/save').status_code == 200


@pytest.mark.parametrize('operation,error,status', [
    ('read_video_metadata', PermissionError('read denied'), 403),
    ('video_hash', OSError('read interrupted'), 400),
    ('video_hash', FileNotFoundError('removed during import'), 404),
])
def test_read_failure_preserves_current_project(current_project, tmp_path, monkeypatch,
                                              operation, error, status):
    client, project, before = current_project
    source = _create_test_video(tmp_path / 'replacement.mp4', duration=2)

    def fail(path):
        raise error

    monkeypatch.setattr(api, operation, fail)
    response = client.post('/api/v1/video/import', json={'path': str(source)})
    assert response.status_code == status, response.text
    assert response.json()['detail']
    assert api._project_state is project
    assert project.model_dump() == before


def test_replacement_during_metadata_read_does_not_bind_old_shape_to_new_content(current_project, tmp_path, monkeypatch):
    client, project, before = current_project
    source = _create_test_video(tmp_path / 'replacement.mp4', duration=2)
    read_metadata = api.read_video_metadata

    def replaced(path):
        metadata = read_metadata(path)
        path.write_bytes(b'different content after metadata read')
        return metadata

    monkeypatch.setattr(api, 'read_video_metadata', replaced)
    response = client.post('/api/v1/video/import', json={'path': str(source)})
    assert response.status_code == 409
    assert api._project_state is project and project.model_dump() == before


def test_project_is_replaced_only_after_import_validation(current_project, tmp_path, monkeypatch):
    client, project, before = current_project
    source = _create_test_video(tmp_path / 'replacement.mp4', duration=2)
    entered, release = Event(), Event()
    real_hash = api.video_hash

    def blocked_hash(path):
        entered.set()
        assert release.wait(5)
        return real_hash(path)

    monkeypatch.setattr(api, 'video_hash', blocked_hash)
    with ThreadPoolExecutor(1) as worker:
        importing = worker.submit(client.post, '/api/v1/video/import', json={'path': str(source)})
        try:
            assert entered.wait(5)
            assert client.get('/api/v1/project/status').json()['video_path'] == before['video_path']
            assert api._project_state is project
            assert project.model_dump() == before
            assert client.post('/api/v1/project/save').status_code == 409
        finally:
            release.set()
        response = importing.result(timeout=5)

    assert response.status_code == 200, response.text
    current = api._project_state
    assert current is not project
    assert current.video_path == str(source.resolve())
    assert current.video.filename == 'replacement.mp4'
    assert current.project_name == f'replacement_{real_hash(source)[:8]}'
    assert current.analysis_status == 'imported'
    assert current.shots == []
    assert current.library_project_id is None
    assert current.display_name == ''
    assert current.audio.status == 'pending'
    assert current.progress.overall_progress == 0
    assert project.model_dump() == before
