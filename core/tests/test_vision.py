from pathlib import Path

import numpy as np
from PIL import Image

from recipe.ae_recipe import generate_ae_recipe
from schemas.shot import Shot, TimeRange
from schemas.vision import (
    AEHypothesis,
    Motion,
    Observation,
    Typography,
    VisionAnalysis,
    VisualEffect,
)
from vision.analyzer import ShotAnalyzer, update_shot_with_analysis
from vision.cache import VisionCache
from vision.mock import MockVisionProvider
from vision.parser import parse_vision_output
from vision.provider import ShotContext


def _make_test_image(path: Path, color: tuple[int, int, int] = (128, 128, 128)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((120, 160, 3), color, dtype=np.uint8)).save(path)
    return path


def test_mock_provider_returns_valid_schema(tmp_path):
    provider = MockVisionProvider()
    shot_dir = tmp_path / "mock_shot"
    shot_dir.mkdir(parents=True, exist_ok=True)

    images = [_make_test_image(shot_dir / f"frame_{i:02d}.jpg") for i in range(3)]
    context = ShotContext(
        shot_id="shot_001",
        start_time=0.0,
        end_time=1.0,
        frame_count=3,
    )

    result = provider.analyze_shot(images, context)

    assert isinstance(result, VisionAnalysis)
    assert result.observations.subject_type == "character"
    assert result.motion.type == "push_in"
    assert result.typography.has_text is True
    assert len(result.visual_effects) >= 1
    assert result.analysis_error is None

    info = provider.get_model_info()
    assert info["provider"] == "mock"


def test_schema_rejects_invalid_values_with_relaxed_fallback():
    raw = """
    {
      "observations": {
        "subject_type": "not_a_valid_type",
        "subject_position": "center",
        "background_type": "photo",
        "depth_layers": 2
      },
      "motion": {
        "type": "push_in",
        "strength": 0.5,
        "confidence": 0.9
      },
      "typography": {
        "has_text": false,
        "position": "unknown",
        "style": "unknown"
      },
      "visual_effects": [
        {"type": "glow", "confidence": 0.7}
      ],
      "ae_hypothesis": {
        "possible_method": "2.5D parallax",
        "possible_effect": "Glow",
        "possible_transition": "unknown"
      }
    }
    """

    result = parse_vision_output(raw)
    assert isinstance(result, VisionAnalysis)
    # 非法枚举值应被容错为 unknown
    assert result.observations.subject_type == "unknown"
    assert result.motion.type == "push_in"


def test_parser_handles_markdown_fenced_output():
    raw = """
Here is the analysis:

```json
{
  "observations": {
    "subject_type": "character",
    "subject_position": "center",
    "background_type": "illustration",
    "depth_layers": 1
  },
  "motion": {"type": "static", "strength": 0.0, "confidence": 0.95},
  "typography": {"has_text": false, "position": "unknown", "style": "unknown"},
  "visual_effects": [],
  "ae_hypothesis": {"possible_method": "unknown"}
}
```
"""

    result = parse_vision_output(raw)
    assert isinstance(result, VisionAnalysis)
    assert result.observations.subject_type == "character"
    assert result.motion.type == "static"


def test_parser_returns_error_for_invalid_json():
    raw = "This is not JSON at all."
    result = parse_vision_output(raw)
    assert result.analysis_error is not None
    assert "无法从模型输出解析 JSON" in result.analysis_error


def test_cache_roundtrip(tmp_path: Path):
    cache = VisionCache(tmp_path / "vision_cache")
    shot_dir = tmp_path / "shot_001"
    shot_dir.mkdir(parents=True, exist_ok=True)

    images = [_make_test_image(shot_dir / f"frame_{i:02d}.jpg") for i in range(3)]
    result = VisionAnalysis(
        observations=Observation(subject_type="object"),
        motion=Motion(type="pan_left", strength=0.3, confidence=0.7),
        typography=Typography(has_text=False),
        visual_effects=[VisualEffect(type="blur", confidence=0.6)],
        ae_hypothesis=AEHypothesis(possible_effect="Blur"),
    )

    cache.set("shot_001", images, "mock-v1", "v2", result)
    cached = cache.get("shot_001", images, "mock-v1", "v2")

    assert cached is not None
    assert cached.observations.subject_type == "object"
    assert cached.motion.type == "pan_left"


def test_shot_analyzer_uses_cache(tmp_path: Path):
    provider = MockVisionProvider()
    cache = VisionCache(tmp_path / "vision_cache")
    analyzer = ShotAnalyzer(provider=provider, cache=cache)

    shot_dir = tmp_path / "shots" / "shot_001"
    shot_dir.mkdir(parents=True, exist_ok=True)
    images = [_make_test_image(shot_dir / f"frame_{i:02d}.jpg") for i in range(3)]

    shot = Shot(
        shot_id="shot_001",
        time=TimeRange(start=0.0, end=1.0, duration=1.0),
        frames=[p.name for p in images],
    )

    result1 = analyzer.analyze(shot, tmp_path)
    result2 = analyzer.analyze(shot, tmp_path)

    assert result1.observations.subject_type == "character"
    assert result2.observations.subject_type == "character"


def test_pipeline_shot_to_recipe(tmp_path: Path):
    provider = MockVisionProvider()
    analyzer = ShotAnalyzer(provider=provider)

    shot_dir = tmp_path / "shots" / "shot_001"
    shot_dir.mkdir(parents=True, exist_ok=True)
    images = [_make_test_image(shot_dir / f"frame_{i:02d}.jpg") for i in range(3)]

    shot = Shot(
        shot_id="shot_001",
        time=TimeRange(start=0.0, end=1.0, duration=1.0),
        frames=[p.name for p in images],
    )

    analysis = analyzer.analyze(shot, tmp_path)
    update_shot_with_analysis(shot, analysis)

    recipe = generate_ae_recipe(shot.model_dump())

    assert recipe["camera"]["type"] == "push_in"
    assert any(layer["role"] == "character" for layer in recipe["layers"])
    assert "glow" in recipe["effects"]
    assert recipe["hypothesis"]["possible_effect"] == "Glow"


def test_update_shot_with_analysis_writes_all_fields():
    analysis = VisionAnalysis(
        observations=Observation(subject_type="text"),
        motion=Motion(type="shake", strength=0.8, confidence=0.6),
        typography=Typography(has_text=True, position="top"),
        visual_effects=[VisualEffect(type="noise", confidence=0.7)],
        ae_hypothesis=AEHypothesis(possible_method="Camera Shake"),
    )

    shot = Shot(
        shot_id="shot_002",
        time=TimeRange(start=0.0, end=1.0, duration=1.0),
        frames=[],
    )

    update_shot_with_analysis(shot, analysis)

    assert shot.observations["subject_type"] == "text"
    assert shot.motion["type"] == "shake"
    assert shot.typography["has_text"] is True
    assert shot.visual_effects[0]["type"] == "noise"
    assert shot.ae_hypothesis["possible_method"] == "Camera Shake"
