from pathlib import Path

from app.config import AppConfig
from selection.frames import locate_frame
from selection.models import JobSnapshot, SelectionRequest
from selection.pipeline import run_selection
from selection.static import StaticVisionAnalysis
from tests.test_audio import write_av_video
from vision.analyzer import ShotAnalyzer


def snapshot(tmp_path, path, request):
    config = AppConfig(vision_provider='mock', ocr_provider='mock',
                       vision_cache_dir=tmp_path / 'cache', ocr_cache_dir=tmp_path / 'ocr',
                       typography_cache_dir=tmp_path / 'typography')
    return JobSnapshot(1, path, locate_frame(path, 0).identity.source_hash, request, config, 'record', tmp_path / 'assets')


def test_static_frame_has_exact_evidence_and_no_temporal_conclusions(tmp_path, monkeypatch):
    path = write_av_video(tmp_path / 'source.mp4', duration=1)
    identity = locate_frame(path, .1).identity
    request = SelectionRequest(kind='frame', frame=identity, preview_token='bound')

    def temporal_called(*args, **kwargs):
        raise AssertionError('static analysis called temporal shot pipeline')

    monkeypatch.setattr(ShotAnalyzer, 'analyze', temporal_called)
    result = run_selection(snapshot(tmp_path, path, request), lambda *args: None)
    assert result['kind'] == 'frame' and result['time']['pts'] == identity.pts
    assert result['time']['actual_time'] == 2 / 24
    assert result['frame']['image'] == 'frame.png'
    assert (tmp_path / 'assets/frame.png').exists()
    assert 'motion' not in result['frame'] and 'audio' not in result
    assert result['frame']['ae_recipe']['animation']['status'] == 'not_applicable'
    assert result['frame']['text_regions'] == [] and 'typography_tracks' not in result['frame']
    forged = StaticVisionAnalysis.model_validate({'motion': {'type': 'push_in'}, 'transition': 'wipe'})
    assert 'motion' not in forged.model_dump() and 'transition' not in forged.model_dump()


def test_clip_separates_cross_cut_motion_and_retains_source_coordinates(tmp_path):
    path = write_av_video(tmp_path / 'source.mp4', duration=4, cuts=(1, 2, 3))
    request = SelectionRequest(kind='clip', start=.9, end=3.1)
    result = run_selection(snapshot(tmp_path, path, request), lambda *args: None)
    assert [(s['time']['start'], s['time']['end']) for s in result['shots']] == [(.9, 1), (1, 2), (2, 3), (3, 3.1)]
    assert result['shots'][0]['rhythm']['status'] == 'not_cut'
    assert result['audio']['tempo_bpm'] is None and result['audio']['beat_times'] == []
    for shot in result['shots']:
        assert all(shot['time']['start'] <= f['actual_time'] < shot['time']['end'] for f in shot['frame_identities'])
        assert all(Path(tmp_path / 'assets/shots' / shot['shot_id'] / f).exists() for f in shot['frames'])
        assert all(shot['time']['start'] <= r['frame_timestamp'] < shot['time']['end'] for r in shot['text_regions'])


def test_one_real_frame_in_clip_does_not_generate_motion_or_animation(tmp_path):
    path = write_av_video(tmp_path / 'short.mp4', duration=1)
    result = run_selection(snapshot(tmp_path, path, SelectionRequest(kind='clip', start=.01, end=.06)), lambda *args: None)
    shot = result['shots'][0]
    assert len(shot['frame_identities']) == 1
    assert shot['motion'].get('type', 'unknown') == 'unknown'
    assert shot['motion_summary'].get('fused_confidence', 0) == 0
    assert shot['ae_recipe']['animation']['status'] == 'not_applicable'
    assert 'transform' not in shot['ae_recipe']
    assert result['partial_failures']
