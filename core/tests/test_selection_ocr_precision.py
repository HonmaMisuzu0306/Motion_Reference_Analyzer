import pytest

from ocr.analyzer import ShotOCRAnalyzer
from ocr.paddle_provider import PaddleOCRProvider
from tests.test_audio import write_av_video


def rounded_real_adapter(monkeypatch):
    # Only the expensive native model is substituted; execute the real Paddle region adapter.
    class Engine:
        def predict(self, image):
            return [{'rec_polys': [[[10, 10], [80, 10], [80, 30], [10, 30]]],
                     'rec_texts': ['MRA'], 'rec_scores': [.99]}]

    def init(self):
        self._available = True
        self._version = '3.7.0'
        self._engines = {'japan': Engine()}

    monkeypatch.setattr(PaddleOCRProvider, '_try_init', init)
    return PaddleOCRProvider(['japan'])


def test_strict_ocr_overrides_provider_rounding_for_boundary_and_color(tmp_path, monkeypatch, paddle_metadata):
    provider = rounded_real_adapter(monkeypatch)
    path = write_av_video(tmp_path / 'source.mp4', duration=1)
    result = ShotOCRAnalyzer(provider, strict_range=True).analyze(path, .041, .042)
    assert not result.analysis_error and result.text_regions
    assert result.text_regions[0].frame_timestamp == pytest.approx(1 / 24, abs=1e-12)
    assert .041 <= result.text_regions[0].frame_timestamp < .042
    assert result.typography_tracks[0].color_observation is not None
