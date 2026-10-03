"""M6 reproducible acceptance: encoded AAC/MP4 and real audio algorithms.

Vision and OCR use mock providers in this focused acceptance. No user library is modified.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))

from app import api
from app.config import reset_config
from app.main import app
from audio.analyzer import analyze_audio
from db.connection import set_db_path
from fastapi.testclient import TestClient
from tests.test_audio import write_av_video
from video.scene_detect import detect_scenes


def main():
    out = ROOT / 'output' / 'm6_acceptance'
    out.mkdir(parents=True, exist_ok=True)
    os.environ['VISION_PROVIDER'] = 'mock'
    os.environ['OCR_PROVIDER'] = 'mock'
    for name in ['VISION', 'CV', 'OCR', 'TYPOGRAPHY', 'AUDIO']:
        os.environ[f'{name}_CACHE_DIR'] = str(out / f'{name.lower()}_cache')
    reset_config()
    set_db_path(out / 'library.db')
    api.reset_library()
    api.reset_project_state()
    api.OUTPUT_DIR = out / 'projects'
    source = write_av_video(out / 'rhythm_120bpm.mp4', cuts=(2, 4.25, 6))
    client = TestClient(app)
    assert client.post('/api/v1/video/import', json={'path': str(source)}).status_code == 200
    response = client.post('/api/v1/video/analyze')
    assert response.status_code == 200, response.text
    status = client.get('/api/v1/project/status').json()
    assert status['audio']['status'] == 'ok', status
    assert abs(status['audio']['tempo_bpm'] - 120) < 4
    shots = client.get('/api/v1/shots').json()['shots']
    assert len(shots) == 4
    assert [s['rhythm']['beat_sync'] for s in shots] == [None, True, False, True]
    assert status['rhythm_summary']['synced_cut_count'] == 2
    assert status['rhythm_summary']['measured_cut_count'] == 3
    exported = client.post('/api/v1/export/json').json()
    markdown = client.post('/api/v1/export/markdown').json()
    retry = client.post('/api/v1/video/analyze-audio').json()
    assert retry['audio']['cache_hit']
    delayed = analyze_audio(write_av_video(out / 'delayed_audio.mp4', offset=1.25))
    assert abs(delayed.onset_times[0] - 1.75) < .08
    silent = analyze_audio(write_av_video(out / 'silent.mp4', silent=True, duration=1))
    no_audio = analyze_audio(write_av_video(out / 'no_audio.mp4', audio=False, duration=1))
    shifted_path = write_av_video(out / 'shifted_origin.mp4', origin=10)
    shifted_scenes = detect_scenes(shifted_path)
    assert [(s['start'], s['end']) for s in shifted_scenes] == [(0, 2), (2, 4), (4, 6), (6, 8)]
    shifted_audio = analyze_audio(shifted_path)
    assert min(abs(t - 2) for t in shifted_audio.beat_times) < .08
    assert silent.status == 'silent' and no_audio.status == 'no_audio'
    evidence = {'status': status, 'shots': shots,
                'delayed_first_onset': delayed.onset_times[0],
                'silent_status': silent.status, 'no_audio_status': no_audio.status,
                'shifted_scenes': shifted_scenes,
                'json_path': exported['path'], 'markdown_path': markdown['path'],
                'audio_algorithm': 'real librosa + PyAV AAC decode',
                'vision_ocr': 'mock (focused M6 acceptance)', 'default_library_modified': False}
    (out / 'result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'bpm': status['audio']['tempo_bpm'], 'cuts': [s['rhythm'] for s in shots],
                      'summary': status['rhythm_summary'], 'evidence': str(out / 'result.json')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
