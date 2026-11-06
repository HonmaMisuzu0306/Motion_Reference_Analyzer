from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.main import app


@pytest.mark.parametrize('fail_on', [1, 2])
def test_reanalysis_json_failure_preserves_durable_results(sample_video, monkeypatch, fail_on):
    client = TestClient(app)
    assert client.post('/api/v1/video/import', json={'path': str(sample_video)}).is_success
    assert client.post('/api/v1/video/analyze', json={'mode': 'basic'}).is_success
    pid = client.post('/api/v1/project/save').json()['project_id']
    old = api._project_state.model_copy(deep=True)
    original = api._persist_project_state
    calls = 0

    def fail_once():
        nonlocal calls
        calls += 1
        if calls == fail_on:
            raise OSError('disk write failed')
        return original()

    monkeypatch.setattr(api, '_persist_project_state', fail_once)
    response = client.post('/api/v1/video/analyze', json={'mode': 'basic'})
    if fail_on == 1:
        assert response.status_code == 500
        assert api._project_state.assets_dir == old.assets_dir
        assert api._project_state.shots == old.shots
        assert client.post(f'/api/v1/library/projects/{pid}/load').is_success
        assert api._project_state.assets_dir == old.assets_dir
    else:
        assert response.is_success, response.text
        assert api._project_state.analysis_status == 'completed_with_warnings'
        assets = api._project_state.assets_dir
        assert assets != old.assets_dir
        assert client.post(f'/api/v1/library/projects/{pid}/load').is_success
        assert api._project_state.assets_dir == assets
    assert Path(old.assets_dir, 'project.json').is_file()
