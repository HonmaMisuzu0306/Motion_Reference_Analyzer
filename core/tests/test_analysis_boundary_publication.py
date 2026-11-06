"""Exact scene boundaries and verified source identity gate published motion evidence."""
import json
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from threading import Event

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import api
from app.config import reset_config
from app.main import app
from cv.frame_sampler import sample_frames_for_cv
from schemas.measured_motion import MeasuredMotion
from selection.media import detect_range_scenes
from tests.test_motion_curves import measured_shot
from video.scene_detect import detect_scenes


def write_cut_video(path, *, fps, cut_frame, origin):
    rng = np.random.default_rng(101)
    first = rng.integers(0, 80, (96, 128, 3), dtype=np.uint8)
    first[:, :, 2] += 150
    second = rng.integers(0, 80, (96, 128, 3), dtype=np.uint8)
    second[:, :, 0] += 150
    with av.open(str(path), 'w') as container:
        stream = container.add_stream('libx264', rate=fps)
        stream.width, stream.height, stream.pix_fmt = 128, 96, 'yuv420p'
        for i in range(36):
            frame = av.VideoFrame.from_ndarray(first if i < cut_frame else second, format='bgr24')
            frame.pts, frame.time_base = i + origin * fps, Fraction(1, fps)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


@pytest.mark.parametrize('pipeline', ['full', 'selection'])
@pytest.mark.parametrize('fps,cut_frame', [(24, 10), (30, 11)])
@pytest.mark.parametrize('origin', [0, 10])
def test_cv_frame_ownership_matches_exact_cut_in_both_pipelines(tmp_path, pipeline, fps, cut_frame, origin):
    path = write_cut_video(tmp_path / 'cut.mp4', fps=fps, cut_frame=cut_frame, origin=origin)
    ranges = (detect_scenes(path) if pipeline == 'full' else
              [item.model_dump() for item in detect_range_scenes(path, 0, 36 / fps)])
    assert len(ranges) == 2
    before = sample_frames_for_cv(path, ranges[0]['start'], ranges[0]['end'], target_fps=fps)
    after = sample_frames_for_cv(path, ranges[1]['start'], ranges[1]['end'], target_fps=fps)
    assert (before[-1]['timestamp'], after[0]['timestamp']) == pytest.approx(
        ((cut_frame - 1) / fps, cut_frame / fps), abs=1e-9), ranges
    assert len(before) == cut_frame and len(after) == 36 - cut_frame
    assert ranges[0]['end'] == pytest.approx(cut_frame / fps, abs=1e-9)
    assert ranges[1]['start'] == pytest.approx(cut_frame / fps, abs=1e-9)


@pytest.fixture
def rejected_source_run(tmp_path, monkeypatch, sample_video):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUTO_SAVE_TO_LIBRARY', 'false')
    reset_config()
    source = tmp_path / 'source.mp4'
    source.write_bytes(sample_video.read_bytes())
    measured = measured_shot([0, .1, 0], [0, .5, .9], start=0, end=1)['measured_motion']
    measured.update(frame_width=320, frame_height=240)
    for point in measured['trajectory']:
        dx = point['translation_x_ratio'] * 320
        point.update(translation_x_px=dx, matrix=((1, 0, dx), (0, 1, 0)))
    evidence = MeasuredMotion.model_validate(measured)

    def replace_after_decoding(*args, **kwargs):
        source.write_bytes(b'replaced during analysis')
        return evidence

    monkeypatch.setattr(api, 'detect_scenes', lambda _: [
        {'shot_id': 'unverified_shot', 'start': 0, 'end': 1, 'duration': 1}])
    monkeypatch.setattr(api, 'analyze_shot_motion', replace_after_decoding)
    with TestClient(app) as client:
        assert client.post('/api/v1/video/import', json={'path': str(source)}).status_code == 200
        assert client.get('/api/v1/shots').json()['shots'] == []
        response = client.post('/api/v1/video/analyze', json={'mode': 'basic'})
        assert response.status_code == 409, response.text
        assert api._project_state.analysis_status == 'error'
        yield client


def test_rejected_source_run_does_not_publish_new_shots(rejected_source_run):
    client = rejected_source_run
    assert client.get('/api/v1/shots').json()['shots'] == []
    assert client.get('/api/v1/shots/unverified_shot').status_code in (404, 409)


def test_rejected_source_run_cannot_export_ae(rejected_source_run):
    response = rejected_source_run.post('/api/v1/shots/unverified_shot/export/ae')
    assert response.status_code in (400, 404, 409), response.text
    assert list(api.OUTPUT_DIR.rglob('*.jsx')) == []


def test_rejected_source_run_json_export_contains_no_unverified_analysis(rejected_source_run):
    response = rejected_source_run.post('/api/v1/export/json')
    if response.status_code == 200:
        assert response.json()['data']['shots'] == []
        saved = json.loads(Path(response.json()['path']).read_text(encoding='utf-8'))
        assert saved['shots'] == []
    else:
        assert response.status_code in (400, 409)


def test_rejected_source_run_markdown_export_contains_no_unverified_analysis(rejected_source_run):
    response = rejected_source_run.post('/api/v1/export/markdown')
    if response.status_code == 200:
        text = Path(response.json()['path']).read_text(encoding='utf-8')
        assert 'unverified_shot' not in text
    else:
        assert response.status_code in (400, 409)


def test_rejected_source_run_cannot_save_unverified_analysis_to_library(rejected_source_run):
    response = rejected_source_run.post('/api/v1/library/save')
    assert response.status_code >= 400, response.text
    assert api._get_library().list_projects() == []


def measurement_for_range(start):
    measured = measured_shot([0, .1, 0], [start, start + .5, start + .9],
                             start=start, end=start + 1)['measured_motion']
    measured.update(frame_width=320, frame_height=240)
    for point in measured['trajectory']:
        dx = point['translation_x_ratio'] * 320
        point.update(translation_x_px=dx, matrix=((1, 0, dx), (0, 1, 0)))
    return MeasuredMotion.model_validate(measured)


@pytest.mark.parametrize('replace_source', [False, True])
def test_analysis_publishes_one_verified_snapshot_and_preserves_previous_assets(
        tmp_path, monkeypatch, sample_video, replace_source):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUTO_SAVE_TO_LIBRARY', 'false')
    reset_config()
    source = tmp_path / 'source.mp4'
    source.write_bytes(sample_video.read_bytes())
    monkeypatch.setattr(api, 'detect_scenes', lambda _: [
        {'shot_id': 'verified_shot', 'start': 0, 'end': 1, 'duration': 1}])
    monkeypatch.setattr(api, 'analyze_shot_motion', lambda *args, **kwargs: measurement_for_range(0))
    with TestClient(app) as client:
        assert client.post('/api/v1/video/import', json={'path': str(source)}).status_code == 200
        first = client.post('/api/v1/video/analyze', json={'mode': 'basic'})
        assert first.status_code == 200, first.text
        original = api._project_state
        original_shots = client.get('/api/v1/shots').json()['shots']
        original_assets = original.assets_dir
        original_audio = original.audio.model_dump()
        original_rhythm = original.rhythm_summary.model_dump()
        original_hash = original.source_hash
        image = Path(original_assets) / 'shots/verified_shot/frame_01.jpg'
        original_image = image.read_bytes()
        entered, release = Event(), Event()

        def blocked_motion(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            if replace_source:
                source.write_bytes(b'replaced during reanalysis')
            return measurement_for_range(1)

        monkeypatch.setattr(api, 'detect_scenes', lambda _: [
            {'shot_id': 'new_shot', 'start': 1, 'end': 2, 'duration': 1}])
        monkeypatch.setattr(api, 'analyze_shot_motion', blocked_motion)
        with ThreadPoolExecutor(1) as worker:
            analysis = worker.submit(client.post, '/api/v1/video/analyze', json={'mode': 'basic'})
            try:
                assert entered.wait(5)
                assert api._project_state is original
                assert api._project_state.assets_dir == original_assets
                assert api._project_state.audio.model_dump() == original_audio
                assert api._project_state.rhythm_summary.model_dump() == original_rhythm
                assert client.get('/api/v1/shots').json()['shots'] == original_shots
                assert client.get('/api/v1/shots/verified_shot').status_code == 200
                assert client.get('/api/v1/shots/new_shot').status_code == 404
                exported = client.post('/api/v1/export/json')
                assert exported.status_code == 200, exported.text
                assert exported.json()['data']['shots'] == original_shots
                persisted = json.loads(Path(exported.json()['path']).read_text(encoding='utf-8'))
                assert persisted['shots'] == original_shots
                markdown = client.post('/api/v1/export/markdown')
                assert markdown.status_code == 200, markdown.text
                text = Path(markdown.json()['path']).read_text(encoding='utf-8')
                assert 'verified_shot' in text and 'new_shot' not in text
                assert client.post('/api/v1/shots/verified_shot/export/ae').status_code == 409
                assert client.post('/api/v1/library/save').status_code == 409
            finally:
                release.set()
            result = analysis.result(timeout=10)
        assert image.read_bytes() == original_image
        assert api._project_state.source_hash == original_hash
        if replace_source:
            assert result.status_code == 409, result.text
            assert api._project_state is original
            assert api._project_state.assets_dir == original_assets
            assert api._project_state.audio.model_dump() == original_audio
            assert api._project_state.rhythm_summary.model_dump() == original_rhythm
            assert client.get('/api/v1/shots').json()['shots'] == original_shots
        else:
            assert result.status_code == 200, result.text
            assert api._project_state is not original
            assert api._project_state.assets_dir != original_assets
            shots = client.get('/api/v1/shots').json()['shots']
            assert [shot['shot_id'] for shot in shots] == ['new_shot']
            assert shots == result.json()['shots']
            assert shots[0]['measured_motion']['trajectory_status'] == 'complete'
            assert client.post('/api/v1/shots/new_shot/export/ae').status_code == 200


def test_manual_save_cannot_bind_verified_analysis_to_replaced_source(tmp_path, monkeypatch, sample_video):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUTO_SAVE_TO_LIBRARY', 'false')
    reset_config()
    source = tmp_path / 'source.mp4'
    source.write_bytes(sample_video.read_bytes())
    monkeypatch.setattr(api, 'detect_scenes', lambda _: [
        {'shot_id': 'verified_shot', 'start': 0, 'end': 1, 'duration': 1}])
    monkeypatch.setattr(api, 'analyze_shot_motion', lambda *args, **kwargs: measurement_for_range(0))
    with TestClient(app) as client:
        assert client.post('/api/v1/video/import', json={'path': str(source)}).status_code == 200
        analyzed = client.post('/api/v1/video/analyze', json={'mode': 'basic'})
        assert analyzed.status_code == 200, analyzed.text
        before = api._project_state.model_dump()
        source.write_bytes(b'replaced after successful analysis but before manual save')
        saved = client.post('/api/v1/library/save')
        assert saved.status_code == 409, saved.text
        assert client.post('/api/v1/project/save').status_code == 409
        assert api._get_library().list_projects() == []
        assert api._project_state.library_project_id is None
        assert api._project_state.source_hash == before['source_hash']
        assert [shot.model_dump() for shot in api._project_state.shots] == before['shots']
