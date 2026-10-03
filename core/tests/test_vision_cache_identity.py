"""Vision cache identity regressions without real model requests."""

import os

import pytest

from schemas.shot import Shot, TimeRange
from schemas.vision import Observation, VisionAnalysis
from vision.analyzer import ShotAnalyzer
from vision.cache import VisionCache


def test_equal_frame_metadata_from_different_videos_cannot_share_result(tmp_path):
    first, second = tmp_path / "a" / "frame_01.jpg", tmp_path / "b" / "frame_01.jpg"
    for image, content in ((first, b"first"), (second, b"other")):
        image.parent.mkdir()
        image.write_bytes(content)
        os.utime(image, (1700000000, 1700000000))
    cache = VisionCache(tmp_path / "cache")
    cache.set("shot_001", [first], "qwen", "v2", VisionAnalysis())
    assert cache.get("shot_001", [second], "qwen", "v2") is None


def test_reversed_temporal_frame_order_cannot_share_result(tmp_path):
    first, second = tmp_path / "frame_01.jpg", tmp_path / "frame_02.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"other")
    cache = VisionCache(tmp_path / "cache")
    cache.set("shot_001", [first, second], "qwen", "v2", VisionAnalysis())
    assert cache.get("shot_001", [second, first], "qwen", "v2") is None


@pytest.mark.parametrize("changed", [
    {"output_protocol_version": "json-prefill-v2"},
    {"api_base": "server-b"},
    {"num_predict": 4000},
])
def test_shot_analyzer_invalidates_complete_provider_configuration(tmp_path, changed):
    class Provider:
        info = {
            "model_id": "qwen", "output_protocol_version": "json-prefill-v1",
            "api_base": "server-a", "num_predict": 8000,
        }
        subject = "object"

        def get_model_info(self):
            return self.info

        def analyze_shot(self, images, context):
            return VisionAnalysis(observations=Observation(subject_type=self.subject))

    image = tmp_path / "shots" / "shot_001" / "frame_01.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    shot = Shot(shot_id="shot_001", time=TimeRange(start=0, end=1, duration=1), frames=[image.name])
    provider = Provider()
    analyzer = ShotAnalyzer(provider, cache=VisionCache(tmp_path / "cache"))
    assert analyzer.analyze(shot, tmp_path).observations.subject_type == "object"
    provider.info = provider.info | changed
    provider.subject = "text"
    assert analyzer.analyze(shot, tmp_path).observations.subject_type == "text"
    provider.subject = "object"
    assert analyzer.analyze(shot, tmp_path).observations.subject_type == "text"
