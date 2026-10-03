import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ocr.analyzer import ShotOCRAnalyzer
from ocr.paddle_provider import PaddleOCRProvider, _detect_language


def test_v3_provider_predict_and_language(monkeypatch):
    class Engine:
        def __init__(self, **kwargs):
            assert 'show_log' not in kwargs
            assert kwargs['use_doc_unwarping'] is False

        def predict(self, image):
            return [{'rec_texts': ['SUMMER', 'SUMMER'], 'rec_scores': [.96, .92],
                     'rec_polys': [[[10, 10], [80, 10], [80, 30], [10, 30]],
                                   [[110, 10], [180, 10], [180, 30], [110, 30]]]}]

    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=Engine, __version__='3.7.0'))
    provider = PaddleOCRProvider(['en'])
    assert provider.available, provider.get_model_info()
    assert len(provider.analyze_frame(np.zeros((100, 200, 3), dtype=np.uint8))) == 2
    assert _detect_language('こんにちは WORLD') == 'mixed'
    assert _detect_language('你好') == 'zh'
    assert _detect_language('こんにちは') == 'ja'
    assert _detect_language('WORLD') == 'en'


def test_unavailable_provider_is_reported_without_false_no_text(monkeypatch):
    monkeypatch.setitem(sys.modules, 'paddleocr', None)
    result = ShotOCRAnalyzer(PaddleOCRProvider(['en'])).analyze(Path('missing.mp4'), 0, 1)
    assert result.analysis_error
    assert not result.has_text


def test_typography_prompt_accepts_json_braces_and_ocr_text():
    from ocr.typography_prompts import get_typography_prompt
    prompt = get_typography_prompt('SUMMER {title}')
    assert 'SUMMER {title}' in prompt
    assert '"role"' in prompt


def test_typography_cache_roundtrip(tmp_path):
    from ocr.semantic import TypographyCache
    from schemas.typography import TypographyAnalysis
    cache = TypographyCache(tmp_path / 'cache')
    image = tmp_path / 'image.jpg'
    image.write_bytes(b'image')
    analysis = TypographyAnalysis(role='title', confidence=.8)
    cache.set(image, (.1, .1, .4, .1), 'SUMMER', {'model_id': 'qwen'}, analysis)
    assert cache.get(image, (.1, .1, .4, .1), 'SUMMER', {'model_id': 'qwen'}).role == 'title'
