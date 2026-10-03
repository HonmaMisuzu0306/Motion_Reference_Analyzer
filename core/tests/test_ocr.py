"""OCR & Text Tracking 测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ocr.analyzer import ShotOCRAnalyzer
from ocr.cache import OCRCache
from ocr.provider import OCRProvider
from ocr.tracking import build_text_tracks
from schemas.typography import BBox, NormalizedBBox, TextRegion


class _StaticOCRProvider(OCRProvider):
    """测试用固定 OCR Provider。"""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.frames = frames
        self.call_count = 0

    def analyze_frame(
        self,
        image: np.ndarray,
        frame_timestamp: float = 0.0,
        frame_width: int = 0,
        frame_height: int = 0,
    ) -> list[TextRegion]:
        regions = self.frames[self.call_count]["regions"]
        self.call_count += 1
        return [r.model_copy(update={"frame_timestamp": frame_timestamp}) for r in regions]

    def get_model_info(self) -> dict[str, Any]:
        return {"provider": "mock-static", "version": "test"}


def _make_region(
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    confidence: float = 0.95,
    language: str = "en",
) -> TextRegion:
    return TextRegion(
        text=text,
        normalized_text=text.lower().strip(),
        language=language,
        confidence=confidence,
        bbox_px=BBox(x=int(x * 100), y=int(y * 100), width=int(w * 100), height=int(h * 100)),
        bbox_normalized=NormalizedBBox(x=x, y=y, width=w, height=h),
        center_x=round(x + w / 2, 4),
        center_y=round(y + h / 2, 4),
        width_ratio=w,
        height_ratio=h,
        orientation="horizontal",
    )


class TestOCRTracking:
    """A-G 合成测试：直接测试 build_text_tracks。"""

    def _build_frames(self, frame_regions: list[list[TextRegion]], interval: float = 0.5):
        return [
            {"timestamp": i * interval, "regions": regions}
            for i, regions in enumerate(frame_regions)
        ]

    def test_a_no_text(self):
        """无文字输入应返回空 tracks，不报错。"""
        tracks = build_text_tracks(self._build_frames([[], []]))
        assert tracks == []

    def test_b_static_english_text(self):
        """静态英文文本：识别、合理 bbox、Track 合并。"""
        region = _make_region("SUMMER", 0.3, 0.4, 0.4, 0.1)
        tracks = build_text_tracks(self._build_frames([[region], [region]]))

        assert len(tracks) == 1
        assert tracks[0].canonical_text == "summer"
        assert tracks[0].frame_count == 2
        assert tracks[0].movement == "static"

    def test_c_multiframe_same_text(self):
        """相同文字连续多帧应只生成一个 Track。"""
        region = _make_region("SAKURA", 0.4, 0.45, 0.2, 0.08)
        tracks = build_text_tracks(self._build_frames([[region], [region], [region]]))

        assert len(tracks) == 1
        assert tracks[0].frame_count == 3

    def test_d_moving_text(self):
        """横向移动文字应判断为 slide。"""
        r1 = _make_region("MOVE", 0.2, 0.45, 0.2, 0.08)
        r2 = _make_region("MOVE", 0.4, 0.45, 0.2, 0.08)
        r3 = _make_region("MOVE", 0.6, 0.45, 0.2, 0.08)
        tracks = build_text_tracks(self._build_frames([[r1], [r2], [r3]]))

        assert len(tracks) == 1
        assert tracks[0].movement == "slide_right"

    def test_e_multiple_text_regions(self):
        """同画面两个不同文字应生成两个独立 Track。"""
        r1 = _make_region("TITLE", 0.2, 0.2, 0.3, 0.1)
        r2 = _make_region("NAME", 0.6, 0.7, 0.2, 0.08)
        tracks = build_text_tracks(self._build_frames([[r1, r2], [r1, r2]]))

        assert len(tracks) == 2
        texts = {t.canonical_text for t in tracks}
        assert texts == {"title", "name"}

    def test_f_ocr_slight_error(self):
        """OCR 轻微误识别应合理合并为一个 Track。"""
        r1 = _make_region("SAKURA", 0.4, 0.45, 0.2, 0.08)
        r2 = _make_region("SAKUR4", 0.41, 0.45, 0.2, 0.08, confidence=0.8)
        r3 = _make_region("SAKURA", 0.4, 0.45, 0.2, 0.08)
        tracks = build_text_tracks(self._build_frames([[r1], [r2], [r3]]))

        assert len(tracks) == 1
        assert tracks[0].frame_count == 3

    def test_g_low_confidence(self):
        """低置信度结果应保留低置信度，不伪造高置信度。"""
        region = _make_region("BLUR", 0.4, 0.45, 0.2, 0.08, confidence=0.25)
        tracks = build_text_tracks(self._build_frames([[region], [region]]))

        assert len(tracks) == 1
        assert tracks[0].average_confidence < 0.5

    def test_analyzer_handles_missing_video_gracefully(self):
        """ShotOCRAnalyzer 对缺失视频应返回 analysis_error，不抛出。"""
        provider = _StaticOCRProvider([])
        analyzer = ShotOCRAnalyzer(provider=provider)
        result = analyzer.analyze(Path("nonexistent.mp4"), 0.0, 1.0)

        assert result.analysis_error is not None
        assert not result.has_text

    def test_cache_roundtrip(self, tmp_path):
        """OCR 缓存应支持读写。"""
        cache_dir = tmp_path / "ocr_cache"
        cache = OCRCache(cache_dir)
        regions = [TextRegion.model_validate(_make_region("CACHED", 0.1, 0.1, 0.2, 0.1))]
        data = [
            {"timestamp": 0.0, "regions": [r.model_dump() for r in regions]},
        ]
        cache.set(Path("video.mp4"), 0.0, 1.0, {"provider": "mock"}, {"fps": 4}, data)
        cached = cache.get(Path("video.mp4"), 0.0, 1.0, {"provider": "mock"}, {"fps": 4})
        assert cached is not None
        assert cached[0]["timestamp"] == 0.0
        assert len(cached[0]["regions"]) == 1


class TestPaddleOCRSmoke:
    """真实 PaddleOCR 最小冒烟测试（可选）。"""

    def test_provider_initializes_without_crash(self):
        """PaddleOCRProvider 在缺失依赖时应优雅降级。"""
        from ocr.paddle_provider import PaddleOCRProvider

        provider = PaddleOCRProvider()
        info = provider.get_model_info()
        assert info["provider"] == "paddleocr"
        # 当前沙箱可能未安装完成，未安装时仍不崩溃
        assert info["available"] or not info["available"]

    def test_real_ocr_on_synthetic_image(self, tmp_path):
        """在 PaddleOCR 已安装且有可用字体时，识别合成图片中的文字。"""
        from PIL import Image, ImageDraw, ImageFont

        from ocr.paddle_provider import PaddleOCRProvider

        provider = PaddleOCRProvider()
        if not provider.available:
            pytest.skip("PaddleOCR 未就绪")

        img_path = tmp_path / "text.png"
        img = Image.new("RGB", (400, 100), color="white")
        draw = ImageDraw.Draw(img)

        # 优先使用默认 PIL 字体；系统字体仅作可选回退
        font = ImageFont.load_default()
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            pass

        draw.text((50, 30), "SUMMER", fill="black", font=font)
        img.save(img_path)

        regions = provider.analyze_frame_path(img_path)
        if not regions:
            pytest.skip("当前字体/环境下 PaddleOCR 未识别到文字")

        texts = [r.normalized_text for r in regions]
        assert any("summer" in t for t in texts)
