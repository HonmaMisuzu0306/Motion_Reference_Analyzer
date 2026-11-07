"""M6 integration: actual AAC audio, persistence, exports and failure isolation."""
import json

from fastapi.testclient import TestClient

from app import api
from app.main import app
from db import ReferenceLibrary
from db.connection import close_connection, get_db_path
from schemas import Project, Shot, TimeRange
from tests.test_audio import write_av_video
from video.metadata import read_video_metadata


def test_pipeline_audio_library_reopen_and_exports(tmp_path, monkeypatch):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUDIO_CACHE_DIR', str(tmp_path / 'audio-cache'))
    client = TestClient(app)
    path = write_av_video(tmp_path / 'clicks.mp4')
    assert client.post('/api/v1/video/import', json={'path': str(path)}).status_code == 200
    response = client.post('/api/v1/video/analyze')
    assert response.status_code == 200, response.text
    status = client.get('/api/v1/project/status').json()
    assert status['audio']['status'] == 'ok'
    assert 116 < status['audio']['tempo_bpm'] < 124
    assert status['rhythm_summary']['cut_count'] == 3
    assert status['rhythm_summary']['synced_cut_count'] == 3
    shots = client.get('/api/v1/shots').json()['shots']
    assert shots[0]['rhythm']['status'] == 'not_cut'
    assert all(s['rhythm']['beat_sync'] is True for s in shots[1:])
    assert shots[1]['ae_recipe']['timing']['nearest_beat'] is not None
    assert status['progress']['stages']['audio_analysis']['status'] == 'completed'

    pid = status['library_project_id']
    sid = client.get(f'/api/v1/library/shots?project_id={pid}').json()['shots'][1]['id']
    assert client.get(f'/api/v1/library/shots/{sid}').json()['rhythm']['beat_sync'] is True
    api.reset_library()
    api.reset_project_state()
    assert client.post(f'/api/v1/library/projects/{pid}/load').status_code == 200
    restored = client.get('/api/v1/project/status').json()
    assert restored['audio'] == status['audio']
    assert restored['message'] == status['message']
    assert restored['video']['has_audio'] is True
    restored_shots = client.get('/api/v1/shots').json()['shots']
    assert restored_shots[1]['rhythm'] == shots[1]['rhythm']
    exported = client.post('/api/v1/export/json').json()
    with open(exported['path'], encoding='utf-8') as file:
        saved = json.load(file)
    assert saved['audio']['beat_times'] == status['audio']['beat_times']
    assert saved['rhythm_summary']['synced_cut_count'] == 3
    markdown = client.post('/api/v1/export/markdown').json()['markdown']
    assert 'Rhythm' in markdown and 'BPM' in markdown and '80' in markdown
    assert '切镜偏差' in markdown


def test_audio_only_retry_is_cached_and_import_clears_previous_result(tmp_path, monkeypatch):
    monkeypatch.setenv('AUDIO_CACHE_DIR', str(tmp_path / 'audio-cache'))
    client = TestClient(app)
    source = write_av_video(tmp_path / 'click.mp4')
    client.post('/api/v1/video/import', json={'path': str(source)})
    assert client.post('/api/v1/video/analyze-audio').json()['audio']['status'] == 'ok'
    assert client.post('/api/v1/video/analyze-audio').json()['audio']['cache_hit'] is True
    assert client.post('/api/v1/video/analyze-audio', json={'force': True}).json()['audio']['cache_hit'] is False
    silent = write_av_video(tmp_path / 'mute.mp4', audio=False, duration=1)
    client.post('/api/v1/video/import', json={'path': str(silent)})
    assert client.get('/api/v1/project/status').json()['audio']['status'] == 'pending'
    no_audio = client.post('/api/v1/video/analyze-audio').json()
    assert no_audio['audio']['status'] == 'no_audio'
    assert no_audio['rhythm_summary']['sync_ratio'] is None


def test_audio_failure_keeps_other_shot_results_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUDIO_CACHE_DIR', str(tmp_path / 'audio-cache'))
    client = TestClient(app)
    source = write_av_video(tmp_path / 'fail.mp4')
    client.post('/api/v1/video/import', json={'path': str(source)})
    from audio import decoder
    original = decoder.decode_audio

    def fail(*args, **kwargs):
        raise RuntimeError('test decoder failure')

    monkeypatch.setattr('audio.analyzer.decode_audio', fail)
    assert client.post('/api/v1/video/analyze').status_code == 200
    status = client.get('/api/v1/project/status').json()
    assert status['status'] == 'completed_with_warnings'
    assert status['audio']['status'] == 'error'
    assert status['progress']['stages']['audio_analysis']['status'] == 'error'
    shots = client.get('/api/v1/shots').json()['shots']
    assert shots[1]['observations'] and shots[1]['ae_recipe']
    assert shots[1]['rhythm']['beat_sync'] is None
    monkeypatch.setattr('audio.analyzer.decode_audio', original)
    assert client.post('/api/v1/video/analyze-audio').json()['audio']['status'] == 'ok'
    recovered = client.get('/api/v1/project/status').json()
    assert recovered['status'] == 'done'
    stage = recovered['progress']['stages']['audio_analysis']
    assert stage['failed'] == 0 and stage['completed'] == stage['total'] == 1
    assert recovered['message']


def test_audio_endpoint_respects_project_guard_and_requires_source():
    client = TestClient(app)
    assert client.post('/api/v1/video/analyze-audio').status_code == 400
    with api._project_operation_lock:
        assert client.post('/api/v1/video/analyze-audio').status_code == 409


def test_video_source_serves_ranges_for_timeline_playback(tmp_path):
    client = TestClient(app)
    assert client.get('/api/v1/video/source').status_code == 400
    path = write_av_video(tmp_path / 'source.mp4', duration=1)
    client.post('/api/v1/video/import', json={'path': str(path)})
    response = client.get('/api/v1/video/source', headers={'Range': 'bytes=0-31'})
    assert response.status_code == 206
    assert response.content == path.read_bytes()[:32]
    assert response.headers['content-range'] == f'bytes 0-31/{path.stat().st_size}'


def test_shifted_project_video_endpoint_serves_normalized_playback_copy(tmp_path):
    import av

    client = TestClient(app)
    path = write_av_video(tmp_path / 'shifted.mp4', origin=10)
    client.post('/api/v1/video/import', json={'path': str(path)})
    response = client.get('/api/v1/video/source')
    assert response.status_code == 200
    preview = tmp_path / 'served.mp4'
    preview.write_bytes(response.content)
    with av.open(str(preview)) as container:
        stream = container.streams.video[0]
        assert float(stream.start_time * stream.time_base) == 0
    pid = api._get_library().save_analysis(Project(video_path=str(path),
        shots=[Shot(shot_id='shifted', time=TimeRange(start=2, end=4, duration=2))]))
    sid = api._get_library().list_shots(pid)[0].id
    preview.write_bytes(client.get(f'/api/v1/library/shots/{sid}/source').content)
    with av.open(str(preview)) as container:
        stream = container.streams.video[0]
        assert float(stream.start_time * stream.time_base) == 0


def test_schema3_migration_preserves_shot_ids_and_manual_tags():
    library = ReferenceLibrary()
    pid = library.save_analysis(Project(project_name='legacy', shots=[
        Shot(shot_id='old', time=TimeRange(start=0, end=1, duration=1), observations={'subject_type': 'character'})]))
    shot = library.list_shots(pid)[0]
    library.set_manual_tags_by_id(shot.id, ['favorite'])
    conn = library._conn
    # Recreate the actual schema3 by removing only the M6 additive columns.
    for table, column in [('projects', 'audio_json'), ('projects', 'rhythm_summary_json'),
                          ('projects', 'video_has_audio'), ('shots', 'rhythm_json')]:
        conn.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
    conn.execute('PRAGMA user_version=3')
    conn.commit()
    close_connection()
    reopened = ReferenceLibrary()
    assert reopened.get_shot(shot.id).manual_tags == ['favorite']
    assert reopened.get_shot(shot.id).observations['subject_type'] == 'character'
    assert reopened.get_shot(shot.id).rhythm == {}
    assert reopened.get_project(pid).audio == {}
    assert reopened._conn.execute('PRAGMA user_version').fetchone()[0] == 6
    assert reopened._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    assert get_db_path().exists()


def test_nonzero_origin_legacy_shots_require_reanalysis_and_do_not_pollute_new_sync(tmp_path, monkeypatch):
    from schemas import VideoInfo

    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    source = write_av_video(tmp_path / 'legacy-shifted.mp4', origin=10)
    legacy = Project(project_name='legacy-shifted', video_path=str(source),
                     video=VideoInfo(**read_video_metadata(source)), analysis_status='done',
                     shots=[Shot(shot_id=f'shot_{i:03d}', time=TimeRange(start=start, end=end, duration=end-start))
                            for i, (start, end) in enumerate([(0, 12), (12, 14), (14, 16)], 1)])
    pid = api._get_library().save_analysis(legacy)
    legacy_ids = [shot.id for shot in api._get_library().list_shots(pid)]
    client = TestClient(app)
    assert client.post(f'/api/v1/library/projects/{pid}/load').status_code == 200
    retried = client.post('/api/v1/video/analyze-audio').json()
    assert retried['rhythm_summary']['measured_cut_count'] == 0
    assert retried['rhythm_summary']['excluded_shot_count'] == 3
    shots = client.get('/api/v1/shots').json()['shots']
    assert all(s['rhythm']['delta_ms'] is None for s in shots)
    assert all('重新分析视频' in s['rhythm']['message'] for s in shots)
    assert client.post('/api/v1/video/analyze').status_code == 200
    assert client.post(f'/api/v1/library/projects/{pid}/load').status_code == 200
    retried = client.post('/api/v1/video/analyze-audio').json()
    assert retried['rhythm_summary']['synced_cut_count'] == 3
    assert retried['rhythm_summary']['cut_count'] == 3
    # Reopening restores the current analysis; legacy rows remain in the archive.
    assert retried['rhythm_summary']['excluded_shot_count'] == 0
    assert len(client.get('/api/v1/shots').json()['shots']) == 4
    assert all(api._get_library().get_shot(sid).provider_versions['analysis_current'] is False
               for sid in legacy_ids)
