from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.config import reset_config
from app.main import app
from db.connection import set_db_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUTO_SAVE_TO_LIBRARY', 'false')
    reset_config()
    set_db_path(tmp_path / 'library.db')
    api.reset_library()
    api.reset_project_state()
    yield TestClient(app)
    api.reset_library()
    api.reset_project_state()
    reset_config()


def analyze(client, sample_video):
    assert client.post('/api/v1/video/import', json={'path': str(sample_video)}).status_code == 200
    assert client.post('/api/v1/video/analyze').status_code == 200


def test_manual_save_search_inspector_media_recipe_and_restart(client, sample_video):
    analyze(client, sample_video)
    assert client.get('/api/v1/library/projects').json()['projects'] == []
    saved = client.post('/api/v1/library/save')
    assert saved.status_code == 200, saved.text
    pid = saved.json()['project_id']
    found = client.post('/api/v1/search', json={'project_id': pid, 'min_confidence': 0}).json()['shots']
    assert found
    sid = found[0]['id']
    detail = client.get(f'/api/v1/library/shots/{sid}').json()
    assert detail['ae_recipe']
    assert detail['measured_motion']['sampling_target_fps'] == 8
    assert detail['ae_recipe']['measured_motion']['sampling_target_fps'] == 8
    assert detail['ae_recipe']['animation_plan']['source_start'] == detail['start_time']
    assert detail['observations'] != detail['ae_hypothesis']
    assert client.get(f'/api/v1/library/shots/{sid}/thumbnail').status_code == 200
    assert client.get(f'/api/v1/library/shots/{sid}/recipe').json() == detail['ae_recipe']
    exported = client.post(f'/api/v1/library/shots/{sid}/export/recipe')
    assert exported.status_code == 200, exported.text
    import json
    assert json.loads(Path(exported.json()['path']).read_text(encoding='utf-8')) == detail['ae_recipe']
    assert client.get(f'/api/v1/library/shots/{sid}/source', headers={'Range': 'bytes=0-99'}).status_code == 206
    assert client.put(f'/api/v1/library/shots/{sid}/tags', json={'tags': ['favorite']}).status_code == 200
    api.reset_project_state()
    api.reset_library()
    assert client.get(f'/api/v1/library/shots/{sid}').json()['manual_tags'] == ['favorite']
    assert client.post(f'/api/v1/library/projects/{pid}/load').status_code == 200
    assert client.get('/api/v1/shots').json()['shots'][0]['ae_recipe']
    exported_project = client.post('/api/v1/export/json').json()
    reloaded = json.loads(Path(exported_project['path']).read_text(encoding='utf-8'))
    assert reloaded['shots'][0]['measured_motion']['sampling_target_fps'] == 8
    report = client.post('/api/v1/export/markdown').json()
    assert '目标采样率：8 帧/秒' in Path(report['path']).read_text(encoding='utf-8')


def test_sqlite_failure_preserves_analysis_and_retry(client, monkeypatch, sample_video):
    from app.config import get_config
    get_config().auto_save_to_library = True
    real = api._get_library
    def fail():
        raise OSError('disk unavailable')
    monkeypatch.setattr(api, '_get_library', fail)
    analyze(client, sample_video)
    status = client.get('/api/v1/project/status').json()
    assert status['status'] == 'completed_with_warnings'
    assert 'disk unavailable' in status['library_warning']
    assert client.get('/api/v1/shots').json()['shots']
    assert client.post('/api/v1/export/json').status_code == 200
    monkeypatch.setattr(api, '_get_library', real)
    assert client.post('/api/v1/library/save').status_code == 200
    assert client.get('/api/v1/project/status').json()['library_warning'] == ''


def test_typography_failure_keeps_recipe_and_marks_warning(client, monkeypatch, sample_video):
    from ocr.provider import MockOCRProvider
    from schemas.typography import TextRegion, TypographyAnalysis
    from vision.mock import MockVisionProvider

    class DetectedText(MockOCRProvider):
        def analyze_frame(self, image, **kwargs):
            return [TextRegion(text='TITLE', normalized_text='title', confidence=.99,
                               frame_timestamp=kwargs['frame_timestamp'])]

    monkeypatch.setattr(api, 'create_ocr_provider', lambda config: DetectedText())
    monkeypatch.setattr(MockVisionProvider, 'analyze_text_region',
                        lambda *args: TypographyAnalysis(analysis_error='VLM unavailable'))
    analyze(client, sample_video)
    status = client.get('/api/v1/project/status').json()
    assert status['status'] == 'completed_with_warnings'
    assert status['progress']['stages']['typography_analysis']['failed'] > 0
    assert client.get('/api/v1/shots').json()['shots'][0]['ae_recipe']


def test_loaded_versions_keep_distinct_details_and_frames(client, tmp_path, sample_video):
    from schemas import Project, Shot, TimeRange, VideoInfo

    lib = api._get_library()
    shots = []
    for version in ('v1', 'v2'):
        frame = tmp_path / version / 'frame_01.jpg'
        frame.parent.mkdir()
        frame.write_bytes(version.encode())
        shots.append(Shot(shot_id='shot_001', time=TimeRange(start=0, end=1, duration=1),
                          frames=[str(frame)], analysis_version=version,
                          observations={'description': version}))
    pid = lib.save_analysis(Project(project_name='history', video_path=str(sample_video),
                           video=VideoInfo(filename=sample_video.name, duration=5, width=320,
                                           height=240, fps=24, codec='h264'), shots=shots))
    assert client.post(f'/api/v1/library/projects/{pid}/load').status_code == 200
    loaded = client.get('/api/v1/shots').json()['shots']
    assert len({s['library_id'] for s in loaded}) == 2
    for shot in loaded:
        params = {'library_id': shot['library_id']}
        detail = client.get('/api/v1/shots/shot_001', params=params).json()
        assert detail['analysis_version'] == shot['analysis_version']
        frame = client.get('/api/v1/shots/shot_001/frame/frame_01.jpg', params=params)
        assert frame.content == shot['analysis_version'].encode()
    assert client.get('/api/v1/shots/shot_001/frame/frame_01.jpg',
                      params={'library_id': 999999}).status_code == 404


def test_reanalysis_keeps_archived_frame_assets(client, monkeypatch, sample_video):
    assert client.post('/api/v1/video/import', json={'path': str(sample_video)}).status_code == 200
    monkeypatch.setattr(api, 'detect_scenes', lambda path: [
        {'shot_id': 'shot_001', 'start': 0, 'end': 1, 'duration': 1}])
    assert client.post('/api/v1/video/analyze').status_code == 200
    assert client.post('/api/v1/library/save').status_code == 200
    old = client.post('/api/v1/search', json={}).json()['shots'][0]['id']
    before = client.get(f'/api/v1/library/shots/{old}/thumbnail').content
    monkeypatch.setattr(api, 'detect_scenes', lambda path: [
        {'shot_id': 'shot_001', 'start': 2, 'end': 3, 'duration': 1}])
    assert client.post('/api/v1/video/analyze').status_code == 200
    assert client.post('/api/v1/library/save').status_code == 200
    assert client.get(f'/api/v1/library/shots/{old}/thumbnail').content == before
