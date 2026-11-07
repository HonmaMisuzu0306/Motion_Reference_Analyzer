from fastapi.testclient import TestClient

from app import api
from app.main import app
from schemas.audio import AudioAnalysis


def test_audio_retry_rejects_replaced_video_before_decoding(tmp_path, monkeypatch, sample_video):
    path = tmp_path / 'source.mp4'
    path.write_bytes(sample_video.read_bytes())
    client = TestClient(app)
    assert client.post('/api/v1/video/import', json={'path': str(path)}).status_code == 200
    before = api._project_state.model_dump()
    path.write_bytes(b'new source')
    monkeypatch.setattr(api, 'analyze_audio', lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('must reject before audio analysis')))
    response = client.post('/api/v1/video/analyze-audio')
    assert response.status_code == 409
    assert api._project_state.model_dump() == before


def test_audio_retry_does_not_publish_changes_before_source_revalidation(tmp_path, monkeypatch, sample_video):
    path = tmp_path / 'source.mp4'
    path.write_bytes(sample_video.read_bytes())
    client = TestClient(app)
    assert client.post('/api/v1/video/import', json={'path': str(path)}).status_code == 200
    before = api._project_state.model_dump()

    def changed(*args, **kwargs):
        path.write_bytes(b'changed while decoding audio')
        return AudioAnalysis(status='silent', duration=99)

    monkeypatch.setattr(api, 'analyze_audio', changed)
    response = client.post('/api/v1/video/analyze-audio')
    assert response.status_code == 409
    assert api._project_state.model_dump() == before
