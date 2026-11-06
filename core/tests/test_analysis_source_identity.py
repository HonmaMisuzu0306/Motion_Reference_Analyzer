from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.config import get_config, reset_config
from cv.cache import MotionCache
from schemas.measured_motion import MeasuredMotion


@pytest.fixture
def client(monkeypatch, tmp_path, sample_video):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUTO_SAVE_TO_LIBRARY', 'false')
    reset_config()
    from app.main import app
    source = tmp_path / 'source.mp4'
    source.write_bytes(sample_video.read_bytes())
    value = TestClient(app)
    assert value.post('/api/v1/video/import', json={'path': str(source)}).status_code == 200
    return value, source


def test_replaced_import_cannot_be_analyzed_with_stale_metadata(client):
    value, source = client
    source.write_bytes(b'replaced')
    response = value.post('/api/v1/video/analyze', json={'mode': 'basic'})
    assert response.status_code == 409
    assert '重新导入' in response.json()['detail']


def test_changed_source_does_not_publish_motion_cache_or_library(client, monkeypatch):
    value, source = client

    def changed(*args, **kwargs):
        source.write_bytes(b'changed after decoding')
        return MeasuredMotion(status='ok', sample_count=8)

    monkeypatch.setattr(api, 'analyze_shot_motion', changed)
    response = value.post('/api/v1/video/analyze', json={'mode': 'basic'})
    assert response.status_code == 409
    assert '缓存未发布' in response.json()['detail']
    assert list(Path(get_config().cv_cache_dir).glob('*.json')) == []
    assert api._get_library().list_projects() == []
    assert api._project_state.analysis_status == 'error'
    assert api._project_state.progress.stage == 'saving'


def test_multiple_shots_share_one_verified_content_identity(client, monkeypatch):
    value, _ = client
    calls = []
    real_hash = api.video_hash

    def count(path):
        calls.append(path)
        return real_hash(path)

    def unexpected_hash(*args):
        raise AssertionError('per-shot cache must reuse verified source identity')

    monkeypatch.setattr(api, 'video_hash', count)
    monkeypatch.setattr(MotionCache, '_video_fingerprint', unexpected_hash)
    monkeypatch.setattr(api, 'detect_scenes', lambda path: [
        {'shot_id': f'shot_{i + 1:03d}', 'start': i, 'end': i + 1, 'duration': 1} for i in range(4)])
    response = value.post('/api/v1/video/analyze', json={'mode': 'basic'})
    assert response.status_code == 200, response.text
    assert len(calls) == 2  # once before analysis, once before publishing
    assert len(list(Path(get_config().cv_cache_dir).glob('*.json'))) == 4


def test_source_changed_during_ocr_never_publishes_ocr_cache_or_results(client, monkeypatch):
    from ocr.provider import MockOCRProvider

    value, source = client

    class ReplacingOCR(MockOCRProvider):
        def analyze_frame(self, image, **kwargs):
            source.write_bytes(b'changed while OCR was running')
            return []

    monkeypatch.setattr(api, 'create_ocr_provider', lambda config: ReplacingOCR())
    monkeypatch.setattr(api, 'detect_scenes', lambda path: [
        {'shot_id': 'shot_001', 'start': 0, 'end': 1, 'duration': 1}])
    response = value.post('/api/v1/video/analyze')
    assert response.status_code == 409, response.text
    assert value.get('/api/v1/shots').json()['shots'] == []
    assert not list(Path(get_config().ocr_cache_dir).rglob('*.json'))
    assert not list(Path(get_config().cv_cache_dir).rglob('*.json'))
