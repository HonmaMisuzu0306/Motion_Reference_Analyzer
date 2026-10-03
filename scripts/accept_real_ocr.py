"""Explicit real-video acceptance; never substitutes mock OCR or VLM."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
os.environ['OCR_PROVIDER'] = 'paddleocr'
os.environ['VISION_PROVIDER'] = 'qwen3-vl'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

from app import api  # noqa: E402
from app.config import get_config, reset_config  # noqa: E402
from app.main import app  # noqa: E402
from db.connection import set_db_path  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from ocr.analyzer import ShotOCRAnalyzer  # noqa: E402
from ocr.paddle_provider import PaddleOCRProvider  # noqa: E402


def main():
    out = ROOT / 'output' / 'real_ocr_acceptance'
    out.mkdir(exist_ok=True)
    provider = PaddleOCRProvider(['en'])
    info = provider.get_model_info()
    print(info, flush=True)
    assert info['available'], info
    analyzer = ShotOCRAnalyzer(provider, max_frames=12)
    segments = [(0, 1), (1, 2), (3, 5)]
    evidence = []
    for start, end in segments:
        result = analyzer.analyze(ROOT / 'samples/test_typography.mp4', start, end)
        assert result.has_text and not result.analysis_error, result
        print(start, [(t.canonical_text, t.frame_count, t.movement, t.appearance) for t in result.typography_tracks], flush=True)
        evidence.append(result.model_dump())
    assert any(t['canonical_text'] == 'summer' and t['movement'] == 'static' for t in evidence[0]['typography_tracks'])
    assert any(t['canonical_text'] == 'motion' and t['movement'] == 'slide_right' and t['frame_count'] >= 4 for t in evidence[1]['typography_tracks'])
    assert {'title', 'lyrics'} <= {t['canonical_text'] for t in evidence[2]['typography_tracks']}
    for result in evidence:
        for r in result['text_regions']:
            assert 0 < r['confidence'] <= 1
            assert 0 <= r['bbox_normalized']['x'] <= 1
            assert 0 <= r['bbox_normalized']['y'] <= 1
    (out / 'ocr_segments.json').write_text(json.dumps({'provider': info, 'segments': evidence}, indent=2), encoding='utf-8')
    reset_config()
    config = get_config()
    config.ocr_languages = ['en']
    config.ocr_cache_dir = out / 'ocr_cache'
    config.vision_cache_dir = out / 'vision_cache_json_protocol'
    config.typography_cache_dir = out / 'typography_cache'
    config.vision_timeout = 300
    config.ocr_max_frames = 30
    # Reuse initialized real engine; this avoids a second model allocation.
    api.create_ocr_provider = lambda config: provider
    set_db_path(out / 'library.db')
    api.reset_library()
    client = TestClient(app)
    assert client.post('/api/v1/video/import', json={'path': str(ROOT / 'samples/test_typography.mp4')}).status_code == 200
    response = client.post('/api/v1/video/analyze')
    assert response.status_code == 200, response.text
    shots = response.json()['shots']
    assert any(s['text_regions'] for s in shots)
    tracks = [t for s in shots for t in s['typography_tracks']]
    assert tracks and all(t['typography_analysis'] and t['typography_analysis']['confidence'] > 0
                          and not t['typography_analysis'].get('analysis_error') for t in tracks)
    assert all(not s['analysis_error'] for s in shots), shots
    assert any(s['ae_recipe'].get('typography') for s in shots)
    exported = client.post('/api/v1/export/json').json()
    markdown = client.post('/api/v1/export/markdown').json()
    assert 'Typography' in markdown['markdown']
    assert any(s['typography_tracks'] for s in exported['data']['shots'])
    status = client.get('/api/v1/project/status').json()
    assert status['status'] == 'done', status
    (out / 'pipeline.json').write_text(json.dumps({'status': status, 'shots': shots}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('REAL OCR PIPELINE PASS', flush=True)


if __name__ == '__main__':
    main()
