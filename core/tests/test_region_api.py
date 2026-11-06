import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import api, region_api
from app.main import app
from schemas import Shot, TimeRange
from tests.test_region_track import movie, normal_box

SHOT = '/api/v1/shots/s1'


@pytest.fixture
def project(tmp_path):
    client = TestClient(app)
    source = tmp_path / 'region.mp4'
    movie(source)
    assert client.post('/api/v1/video/import', json={'path': str(source)}).is_success
    project = api._project_state
    project.analysis_status = 'done'
    project.shots = [Shot(shot_id='s1', time=TimeRange(start=.15, end=1, duration=.85)),
                     Shot(shot_id='s2', time=TimeRange(start=1, end=1.25, duration=.25))]
    return client, project.source_hash, source


def request_track(client, identity, **updates):
    body = {'identity': identity, 'anchor_time': .25, 'end_time': 1, 'box': normal_box(6).model_dump()}
    return client.post(f'{SHOT}/region-track', json={**body, **updates})


def test_frame_track_and_server_owned_export(project):
    client, identity, _ = project
    result = client.get(f'{SHOT}/region-frame', params={'identity': identity, 'time': .264})
    assert result.is_success, result.text
    entry = result.json()
    assert entry['source_time'] == .25 and entry['source_id'] == identity
    jpeg = base64.b64decode(entry['image_data_url'].split(',')[1], validate=True)
    pixels = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert pixels.shape[:2] == (entry['frame_height'], entry['frame_width']) == (216, 384)
    record = request_track(client, identity, anchor_time=entry['source_time']).json()
    track = record['track']
    assert track['status'] == 'complete' and track['samples'][-1]['source_time'] == 23/24
    export = f"{SHOT}/region-tracks/{record['track_id']}/export/ae"
    rsp = client.post(export, json={'identity': identity})
    assert rsp.is_success, rsp.text
    path = Path(rsp.json()['path'])
    assert path.is_file() and path.is_relative_to(api.OUTPUT_DIR)
    assert 'tracked region center' in path.read_text(encoding='utf8')
    assert client.post(export, json={'identity': identity, 'track': track}).status_code == 422
    assert client.post(export, json={'identity': identity, 'path': 'elsewhere.jsx'}).status_code == 422
    assert client.post(export.replace('/s1/', '/s2/'), json={'identity': identity}).status_code == 404


def test_bounds_identity_and_obsolete_anchor(project):
    client, identity, _ = project
    for time in (.14, 1, -2, 'nan'):
        assert client.get(f'{SHOT}/region-frame', params={'time': time, 'identity': identity}).status_code == 422
    assert client.get(f'{SHOT}/region-frame', params={'time': .2, 'identity': '0'*64}).status_code == 409
    assert request_track(client, identity, end_time=1.1).status_code == 422
    assert request_track(client, identity, anchor_time=.1).status_code == 422
    assert request_track(client, identity, anchor_time=.26).status_code == 409
    assert request_track(client, identity, box={'x': .95, 'y': 0, 'width': .1, 'height': .1}).status_code == 422
    assert request_track(client, identity, path='another.mp4').status_code == 422
    api._project_state.analysis_status = 'imported'
    assert request_track(client, identity).status_code == 409


def test_duplicate_shot_ids_cannot_reuse_a_frame_track_or_export(project):
    client, identity, _ = project
    record = request_track(client, identity).json()
    # Distinct library rows can retain the same display shot id after reopening.
    shots = api._project_state.shots
    shots[0].library_id = 10
    shots.append(shots[1].model_copy(update={'shot_id': 's1', 'library_id': 20}))
    frame = client.get(f'{SHOT}/region-frame', params={'identity': identity, 'time': .25})
    assert frame.status_code == 409 and '相同编号' in frame.json()['detail']
    assert request_track(client, identity).status_code == 409
    export = f"{SHOT}/region-tracks/{record['track_id']}/export/ae"
    assert client.post(export, json={'identity': identity}).status_code == 409
    # Even when the two rows have the same time range, id scopes the stored result.
    shots[-1].time = shots[0].time.model_copy()
    frame = client.get(f'{SHOT}/region-frame', params={'identity': identity, 'time': .25, 'library_id': 20})
    assert frame.status_code == 200
    assert request_track(client, identity, library_id=999).status_code == 404
    second = request_track(client, identity, library_id=20).json()
    export = f"{SHOT}/region-tracks/{second['track_id']}/export/ae"
    assert client.post(export, json={'identity': identity, 'library_id': 10}).status_code == 404
    assert client.post(export, json={'identity': identity, 'library_id': 20}).is_success


def test_replacement_blocks_frame_track_and_cached_export(project):
    client, identity, source = project
    record = request_track(client, identity).json()
    # Keep the original path, length and mtime after an in-place replacement.
    import os
    stat = source.stat()
    data = bytearray(source.read_bytes())
    data[-1] ^= 0x40
    source.write_bytes(data)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert client.get(f'{SHOT}/region-frame', params={'identity': identity, 'time': .25}).status_code == 409
    assert request_track(client, identity).status_code == 409
    export = f"{SHOT}/region-tracks/{record['track_id']}/export/ae"
    assert client.post(export, json={'identity': identity}).status_code == 409
    assert not (api.OUTPUT_DIR/'ae_exports').exists()


def test_eviction_expiry_and_reloaded_working_state(project, monkeypatch):
    client, identity, _ = project
    monkeypatch.setattr(region_api, 'MAX_TRACKS', 1)
    def export_url():
        record = request_track(client, identity).json()
        return f"{SHOT}/region-tracks/{record['track_id']}/export/ae"
    old = export_url()
    current = export_url()
    assert client.post(old, json={'identity': identity}).status_code == 404
    now = region_api.monotonic()
    monkeypatch.setattr(region_api, 'monotonic', lambda: now+region_api.TRACK_TTL_SECONDS+1)
    assert client.post(current, json={'identity': identity}).status_code == 404
    current = export_url()
    api._project_state = api._project_state.model_copy(deep=True)
    assert client.post(current, json={'identity': identity}).status_code == 404


def test_two_pin_uses_only_confirmed_tracks_from_the_same_shot_and_interval(project):
    client, identity, _ = project
    # Two separated pieces of the same left-moving background.
    def background(x, **extra):
        box = dict(x=x, y=.71, width=.07, height=.14)
        return request_track(client, identity, box=box, **extra).raise_for_status().json()['track_id']

    a, b = background(.38), background(.73)
    combine = f'{SHOT}/two-pin-track'
    body = dict(identity=identity, track_a_id=a, track_b_id=b, same_layer_confirmed=True)
    assert client.post(combine, json={**body, 'same_layer_confirmed': False}).status_code == 422
    assert client.post(combine, json={**body, 'track_b_id': a}).status_code == 422
    assert client.post(combine, json={**body, 'samples': []}).status_code == 422
    other_end = background(.73, end_time=.875)
    assert client.post(combine, json={**body, 'track_b_id': other_end}).status_code == 409
    other_anchor = background(.73, anchor_time=.375)
    assert client.post(combine, json={**body, 'track_b_id': other_anchor}).status_code == 409
    assert client.post(combine.replace('/s1/', '/s2/'), json=body).status_code == 404
    answer = client.post(combine, json=body).raise_for_status().json()
    samples = answer['track']['samples']
    assert answer['track']['status'] == 'complete' and len(samples) > 2
    assert samples[0]['source_time'] == .25 and samples[-1]['position_x_px'] < samples[0]['position_x_px']-25
    assert all(abs(p['scale_percent']-100) < .5 and abs(p['rotation_deg']) < .3 for p in samples)
    pair = answer['track_id']
    export = f'{SHOT}/two-pin-tracks/{pair}/export/ae'
    def send(route):
        return client.post(route, json={'identity': identity})
    assert send(export.replace(pair, a)).status_code == 404
    assert send(export.replace('two-pin-tracks', 'region-tracks')).status_code == 404
    file = Path(send(export).raise_for_status().json()['path'])
    assert file.is_file() and file.is_relative_to(api.OUTPUT_DIR/'ae_exports')
    assert send(f'{SHOT}/region-tracks/{a}/export/ae').is_success
    api._project_state = api._project_state.model_copy(deep=True)
    assert send(export).status_code == 404


def test_two_pin_revalidates_source_before_combining_and_exporting(project):
    client, identity, source = project
    a = request_track(client, identity).raise_for_status().json()['track_id']
    b = request_track(client, identity, box=dict(x=.72, y=.66, width=.08, height=.13)).raise_for_status().json()['track_id']
    body = dict(identity=identity, track_a_id=a, track_b_id=b, same_layer_confirmed=True)
    combine = f'{SHOT}/two-pin-track'
    pair = client.post(combine, json=body).raise_for_status().json()['track_id']
    source.write_bytes(b'replaced test video')
    assert client.post(combine, json=body).status_code == 409
    resp = client.post(f'{SHOT}/two-pin-tracks/{pair}/export/ae',json={'identity': identity})
    assert resp.status_code == 409 and not list(api.OUTPUT_DIR.rglob('*.jsx'))


def test_failing_final_source_check_never_publishes_a_script(project, monkeypatch):
    client, identity, _ = project
    record = request_track(client, identity).json()
    export = f"{SHOT}/region-tracks/{record['track_id']}/export/ae"
    destination = api.OUTPUT_DIR/'ae_exports'

    def changed(*_args):
        assert list(destination.glob('*.tmp'))
        raise region_api.PlaybackSourceChanged('source changed before publishing')

    monkeypatch.setattr(region_api, 'check_key', changed)
    assert client.post(export, json={'identity': identity}).status_code == 409
    assert list(destination.iterdir()) == []


def test_source_cannot_change_unnoticed_inside_the_decode(project, monkeypatch):
    client, identity, source = project
    picture = region_api._region_picture
    replaced = []

    def change(file, *args):
        result = picture(file, *args)
        try:
            with source.open('r+b') as writer:
                writer.write(b'changed')
        except PermissionError:
            replaced.append(False)  # Windows deny-write lease
        else:
            replaced.append(True)
        return result

    monkeypatch.setattr(region_api, '_region_picture', change)
    response = client.get(f'{SHOT}/region-frame', params={'time': .25, 'identity': identity})
    assert replaced and response.status_code == (409 if replaced[0] else 200)


def test_conflicting_workspace_change_is_rejected_while_resolving_frame(project, monkeypatch):
    client, identity, source = project
    reading, finish = Event(), Event()
    real = region_api._region_picture

    def delayed(*args):
        reading.set()
        assert finish.wait(5)
        return real(*args)

    monkeypatch.setattr(region_api, '_region_picture', delayed)
    with ThreadPoolExecutor(1) as workers:
        future = workers.submit(client.get, f'{SHOT}/region-frame', params={'identity': identity, 'time': .25})
        try:
            assert reading.wait(5)
            assert client.post('/api/v1/video/import', json={'path': str(source)}).status_code == 409
        finally:
            finish.set()
        assert future.result(timeout=5).is_success
