"""OCR regression checks without loading OCR or VLM models."""

import os
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from ocr.analyzer import ShotOCRAnalyzer
from ocr.cache import OCRCache
from ocr.semantic import TypographyCache, TypographySemanticAnalyzer
from ocr.tracking import build_text_tracks
from ocr.typography_parser import parse_typography_output
from schemas.typography import NormalizedBBox, TextRegion, TypographyAnalysis
from vision.qwen import QwenVisionProvider


def region(text, x, timestamp, confidence=.95):
    return TextRegion(
        text=text, normalized_text=text.lower(), confidence=confidence,
        bbox_normalized=NormalizedBBox(x=x, y=.3, width=.1, height=.1),
        frame_timestamp=timestamp,
    )


def test_identical_text_regions_in_one_frame_keep_independent_tracks():
    frames = [
        {"timestamp": t, "regions": [region("COPY", .1, t), region("COPY", .3, t)]}
        for t in (0, .5)
    ]
    tracks = build_text_tracks(frames)
    assert len(tracks) == 2
    assert [t.frame_count for t in tracks] == [2, 2]
    assert [t.movement for t in tracks] == ["static", "static"]


def test_text_returning_after_long_absence_starts_new_track():
    frames = [
        {"timestamp": 0, "regions": [region("TITLE", .3, 0)]},
        {"timestamp": .5, "regions": []},
        {"timestamp": 1, "regions": []},
        {"timestamp": 20, "regions": [region("TITLE", .3, 20)]},
    ]
    tracks = build_text_tracks(frames)
    assert len(tracks) == 2
    assert [t.duration for t in tracks] == [0, 0]


def test_sparse_long_shot_and_one_missed_sample_stay_connected():
    frames = [
        {"timestamp": t, "regions": [] if t == 20 else [region("TITLE", .3, t)]}
        for t in (0, 10, 20, 30)
    ]
    tracks = build_text_tracks(frames)
    assert len(tracks) == 1
    assert tracks[0].frame_count == 3
    assert tracks[0].duration == 30


def test_ocr_cache_does_not_cross_same_named_video_content(tmp_path):
    first, second = tmp_path / "a" / "same.mp4", tmp_path / "b" / "same.mp4"
    for video, content in ((first, b"aaaa"), (second, b"bbbb")):
        video.parent.mkdir()
        video.write_bytes(content)
        os.utime(video, (1700000000, 1700000000))
    cache = OCRCache(tmp_path / "cache")
    cache.set(first, 0, 1, {}, {}, [{"timestamp": 0, "regions": []}])
    assert cache.get(second, 0, 1, {}, {}) is None


@pytest.mark.parametrize("changed", [{"api_base": "server-b"}, {"num_predict": 8000}])
def test_typography_cache_invalidates_changed_provider_configuration(tmp_path, changed):
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    info = {"model_id": "qwen", "api_base": "server-a", "num_predict": 100}
    cache = TypographyCache(tmp_path / "cache")
    cache.set(image, (.1, .1, .2, .1), "COPY", info, TypographyAnalysis(confidence=.9))
    assert cache.get(image, (.1, .1, .2, .1), "COPY", info | changed) is None


def test_semantic_retries_returned_error_until_success(tmp_path):
    class Provider:
        calls = 0

        def get_model_info(self):
            return {"model_id": "test"}

        def analyze_text_region(self, *args):
            self.calls += 1
            if self.calls < 3:
                return TypographyAnalysis(analysis_error="temporary failure")
            return TypographyAnalysis(role="title", confidence=.9)

    provider = Provider()
    tracks = build_text_tracks([{"timestamp": 0, "regions": [region("COPY", .1, 0)]}])
    result, _ = TypographySemanticAnalyzer(provider, max_retries=2).analyze_tracks(
        tracks, tmp_path / "image.jpg", "shot"
    )
    assert result[0].typography_analysis.role == "title"
    assert provider.calls == 3


def test_exhausted_semantic_error_is_explicit_and_not_cached(tmp_path):
    class Provider:
        def get_model_info(self):
            return {"model_id": "test"}

        def analyze_text_region(self, *args):
            return TypographyAnalysis(confidence=.9, analysis_error="service down")

    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    cache = TypographyCache(tmp_path / "cache")
    tracks = build_text_tracks([{"timestamp": 0, "regions": [region("COPY", .1, 0)]}])
    result, _ = TypographySemanticAnalyzer(Provider(), cache=cache).analyze_tracks(tracks, image, "shot")
    assert result[0].typography_analysis.model_dump().get("analysis_error") == "service down"
    assert not list(cache.cache_dir.glob("*.json"))


def test_failed_typography_cache_entry_is_ignored(tmp_path):
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    cache = TypographyCache(tmp_path / "cache")
    cache.set(image, (.1, .1, .2, .1), "COPY", {},
              TypographyAnalysis(confidence=.9, analysis_error="service down"))
    assert cache.get(image, (.1, .1, .2, .1), "COPY", {}) is None


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null", '{"role": "invalid"}'])
def test_typography_parse_failure_has_explicit_error(raw):
    assert parse_typography_output(raw).model_dump().get("analysis_error")


def test_qwen_connection_failure_has_explicit_error(tmp_path):
    image = tmp_path / "image.jpg"
    Image.new("RGB", (20, 20)).save(image)
    provider = QwenVisionProvider()
    provider._client.close()

    def fail(request):
        raise httpx.ConnectError("service down", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        provider._client = client
        result = provider.analyze_text_region(image, (.1, .1, .4, .4), "COPY", {})
    assert result.model_dump().get("analysis_error")


@pytest.mark.parametrize("cached", [False, True])
def test_track_color_uses_its_observed_frame_and_bbox(tmp_path, monkeypatch, cached):
    class Provider:
        def get_model_info(self):
            return {"provider": "test"}

        def analyze_frame(self, image, frame_timestamp, **kwargs):
            if frame_timestamp < 1:
                return []
            return [region("TITLE", .1 if frame_timestamp < 2 else .3,
                           frame_timestamp, confidence=.8 if frame_timestamp < 2 else .95)]

    blank = np.full((100, 100, 3), 255, dtype=np.uint8)
    title = blank.copy()
    title[28:42, 28:42] = (0, 0, 200)
    frames = [
        {"timestamp": .5, "image": blank, "width": 100, "height": 100},
        {"timestamp": 1.5, "image": title, "width": 100, "height": 100},
        {"timestamp": 2.5, "image": title, "width": 100, "height": 100},
    ]
    monkeypatch.setattr("ocr.analyzer.sample_ocr_frames", lambda *args, **kwargs: frames)
    cache = OCRCache(tmp_path / "cache") if cached else None
    analyzer = ShotOCRAnalyzer(Provider(), cache=cache)
    result = analyzer.analyze(Path("video.mp4"), 0, 3)
    if cached:
        result = analyzer.analyze(Path("video.mp4"), 0, 3)
    assert result.typography_tracks[0].color_observation.dominant_color == "warm"
    assert "mean_rgb=(200,0,0)" in result.typography_tracks[0].color_observation.notes
