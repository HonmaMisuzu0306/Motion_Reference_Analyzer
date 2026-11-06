"""Representative PTS survive persistence; one image cannot imply temporal semantics."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import api
from app.config import reset_config
from app.main import app
from ocr.semantic import TypographySemanticAnalyzer
from schemas import Shot, TimeRange
from schemas.typography import TextRegion, TextTrack, TypographyResult
from selection.static import StaticHypothesis, StaticObservation, StaticVisionAnalysis
from tests.test_analysis_boundary_publication import measurement_for_range
from tests.test_metadata import _create_test_video
from video.frame_sampler import sample_frames
from vision.mock import MockVisionProvider


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    monkeypatch.setenv('AUTO_SAVE_TO_LIBRARY', 'false')
    reset_config()
    with TestClient(app) as value:
        yield value


def analyze(client, path, mode='full'):
    assert client.post('/api/v1/video/import', json={'path': str(path)}).status_code == 200
    response = client.post('/api/v1/video/analyze', json={'mode': mode})
    assert response.status_code == 200, response.text
    return response.json()['shots'][0]


def forbidden_temporal(*args, **kwargs):
    raise AssertionError('Single representative image must not call temporal semantic analysis')


def test_real_one_frame_shot_has_static_semantics_and_no_animation(client, tmp_path, monkeypatch):
    path = _create_test_video(tmp_path / 'one-frame.mp4', duration=1 / 24)
    calls = []

    def static_analysis(self, image, context):
        calls.append((image, context))
        return StaticVisionAnalysis(observations=StaticObservation(composition='single image'),
                                   ae_hypothesis=StaticHypothesis(layer_layout='background and title'))

    monkeypatch.setattr(MockVisionProvider, 'analyze_shot', forbidden_temporal)
    monkeypatch.setattr(MockVisionProvider, 'analyze_static_frame', static_analysis)
    monkeypatch.setattr(TypographySemanticAnalyzer, 'analyze_tracks', forbidden_temporal)
    monkeypatch.setattr(api.ShotOCRAnalyzer, 'analyze', lambda *a, **kw: TypographyResult(
        text_regions=[TextRegion(text='TITLE', frame_timestamp=0, confidence=.9)],
        typography_tracks=[TextTrack(canonical_text='TITLE', appearance='fade', movement='slide_right')]))
    shot = analyze(client, path)
    assert len(calls) == 1 and calls[0][0].is_file()
    assert calls[0][1]['actual_time'] == 0
    assert len(shot['frames']) == 1 and shot['frame_timestamps'] == [0]
    assert shot['observations']['composition'] == 'single image'
    assert shot['motion'] == {} and shot['typography_tracks'] == []
    assert shot['provider_versions']['vision']['analysis_mode'] == 'static_frame'
    assert shot['measured_motion']['sample_count'] == 1
    assert shot['measured_motion']['status'] != 'ok'
    assert '采样帧不足' in shot['measured_motion']['message']
    recipe = shot['ae_recipe']
    assert recipe['layer_layout'] == 'background and title'
    assert recipe['text_layers'][0]['text'] == 'TITLE'
    assert recipe['animation']['status'] == recipe['camera']['status'] == 'not_applicable'
    assert 'animation_plan' not in recipe and 'transform' not in recipe
    assert client.post(f"/api/v1/shots/{shot['shot_id']}/export/ae").status_code == 409


def test_real_multiframe_shot_keeps_temporal_pipeline_and_roundtrips_actual_times(client, tmp_path, monkeypatch):
    path = _create_test_video(tmp_path / 'several-frames.mp4', duration=1)
    monkeypatch.setattr(MockVisionProvider, 'analyze_static_frame', forbidden_temporal)
    expected = [frame['timestamp'] for frame in sample_frames(path, 0, 1, 3)]
    shot = analyze(client, path)
    assert len(shot['frames']) == len(expected) > 1
    assert shot['frame_timestamps'] == expected
    assert len(set(expected)) == len(expected)
    assert all(shot['time']['start'] <= time < shot['time']['end'] for time in expected)
    assert shot['motion']['type'] == 'push_in'
    assert 'animation_plan' in shot['ae_recipe']
    metadata = shot['provider_versions']['representative_frames']
    assert metadata['timestamps'] == expected
    assert metadata['strategy'] == 'nearest-actual-pts-half-open-unique-v1'
    assert metadata['time_origin'] == 'source_video_seconds'
    saved = client.post('/api/v1/library/save')
    assert saved.status_code == 200, saved.text
    pid = saved.json()['project_id']
    library = api._get_library()
    archived = library.list_shots(pid)[0]
    assert archived.provider_versions['representative_frames']['timestamps'] == expected
    detail = client.get(f'/api/v1/library/shots/{archived.id}').json()
    assert detail['frame_timestamps'] == expected
    assert len(detail['frame_paths']) == len(detail['frame_timestamps'])
    assert 'frame_timestamps' not in {row[1] for row in library._conn.execute('PRAGMA table_info(shots)')}
    api.reset_project_state()
    assert client.post(f'/api/v1/library/projects/{pid}/load').status_code == 200
    loaded = client.get(f"/api/v1/shots/{shot['shot_id']}").json()
    assert loaded['frame_timestamps'] == expected
    exported = client.post('/api/v1/export/json').json()
    assert exported['data']['shots'][0]['frame_timestamps'] == expected
    assert json.loads(Path(exported['path']).read_text(encoding='utf-8'))['shots'][0]['frame_timestamps'] == expected


def test_single_representative_image_can_use_independent_reliable_cv_without_semantic_animation(
        client, tmp_path, monkeypatch):
    path = _create_test_video(tmp_path / 'independent-cv.mp4', duration=1)
    monkeypatch.setattr(MockVisionProvider, 'analyze_shot', forbidden_temporal)
    monkeypatch.setattr(api, 'sample_frames', lambda *a, **kw: sample_frames(*a, **kw)[:1])
    monkeypatch.setattr(api, 'analyze_shot_motion', lambda *a, **kw: measurement_for_range(0))
    shot = analyze(client, path)
    assert len(shot['frames']) == 1 and shot['motion'] == {}
    assert shot['typography_tracks'] == []
    recipe = shot['ae_recipe']
    assert recipe['camera']['status'] == recipe['animation']['status'] == 'measured_only'
    assert recipe['animation_plan']['evidence_source'] == 'measured'
    assert recipe['animation_plan']['curves']
    assert recipe['transform']['position_x']['max_value'] == 10
    assert client.post(f"/api/v1/shots/{shot['shot_id']}/export/ae").status_code == 200


def test_basic_single_frame_retains_disabled_model_disclosure(client, tmp_path, monkeypatch):
    path = _create_test_video(tmp_path / 'basic-one-frame.mp4', duration=1 / 24)
    monkeypatch.setattr(api, 'create_vision_provider', forbidden_temporal)
    monkeypatch.setattr(api, 'create_ocr_provider', forbidden_temporal)
    shot = analyze(client, path, mode='basic')
    assert shot['frame_timestamps'] == [0]
    assert shot['provider_versions']['vision']['provider'] == 'disabled'
    assert shot['provider_versions']['ocr']['provider'] == 'disabled'
    assert '已省略' in shot['ae_recipe']['basis']
    assert 'animation_plan' not in shot['ae_recipe']
    report = client.post('/api/v1/export/markdown').json()['markdown']
    assert '基础分析已省略' in report


@pytest.mark.parametrize('timestamps', [[.1, .2], [.1, .1, .2], [0, .5, 1], [0, .5, float('nan')]])
def test_representative_timestamps_must_match_unique_in_range_frames(timestamps):
    with pytest.raises(ValidationError):
        Shot(shot_id='bad', time=TimeRange(start=0, end=1, duration=1),
             frames=['a.jpg', 'b.jpg', 'c.jpg'], frame_timestamps=timestamps)


def test_old_shots_with_no_timestamp_metadata_remain_readable():
    old = Shot(shot_id='old', time=TimeRange(start=0, end=1, duration=1), frames=['legacy.jpg'])
    assert old.frame_timestamps == []
