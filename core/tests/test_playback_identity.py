"""A preview must belong to the analysis whose timeline requested the bytes."""
from pathlib import Path
from shutil import copyfile

from fastapi.testclient import TestClient

from app import api
from app.main import app
from schemas import Project, Shot, TimeRange
from tests.test_audio import write_av_video


def test_old_player_cannot_read_the_new_project(tmp_path):
    client = TestClient(app)
    first = write_av_video(tmp_path / 'first.mp4', duration=1)
    second = write_av_video(tmp_path / 'second.mp4', duration=2)
    client.post('/api/v1/video/import', json={'path': str(first)}).raise_for_status()
    client.post('/api/v1/video/import', json={'path': str(second)}).raise_for_status()
    response = client.get('/api/v1/video/source', params={'identity': str(first)}, headers={'Range': 'bytes=0-31'})
    assert response.status_code == 409
    key = client.get('/api/v1/project/status').json()['video_source_id']
    assert key == client.get('/api/v1/shots').json()['video_source_id']
    current = client.get('/api/v1/video/source', params={'identity': key}, headers={'Range': 'bytes=0-31'})
    assert current.status_code == 206
    assert current.content == second.read_bytes()[:32]


def test_same_path_replaced_is_not_playable_as_old_analysis(tmp_path):
    client = TestClient(app)
    first = write_av_video(tmp_path / 'reference.mp4', duration=1)
    second = write_av_video(tmp_path / 'replacement.mp4', duration=2)
    client.post('/api/v1/video/import', json={'path': str(first)}).raise_for_status()
    saved = Project(video_path=str(first), shots=[Shot(shot_id='01', time=TimeRange(start=0, end=1, duration=1))])
    library = api._get_library()
    pid = library.save_analysis(saved)
    sid = library.list_shots(pid)[0].id
    endpoints = ['/api/v1/video/source', f'/api/v1/library/shots/{sid}/source']
    for url in endpoints:
        assert client.get(url, headers={'Range': 'bytes=32-63'}).content == first.read_bytes()[32:64]
    old_status = client.get('/api/v1/project/status').json()
    copyfile(second, first)
    for url in endpoints:
        assert client.get(url, headers={'Range': 'bytes=32-63'}).status_code == 409
    new_import = client.post('/api/v1/video/import', json={'path': str(first)}).json()
    assert new_import['video_source_id'] != old_status['video_source_id']
    assert client.get(endpoints[0], params={'identity': old_status['video_source_id']}).status_code == 409


def test_removed_explicit_path_never_falls_back_to_a_same_named_sample(tmp_path):
    client = TestClient(app)
    first = write_av_video(tmp_path / 'reference.mp4', duration=1)
    samples = Path(api.OUTPUT_DIR).parent / 'samples'
    samples.mkdir()
    write_av_video(samples / first.name, duration=2)
    client.post('/api/v1/video/import', json={'path': str(first)}).raise_for_status()
    first.unlink()
    assert client.get('/api/v1/video/source').status_code == 404
