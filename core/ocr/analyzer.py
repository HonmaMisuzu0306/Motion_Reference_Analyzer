"""OCR Analyzer：整合采样、识别、追踪与颜色观察。"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ocr.cache import OCRCache
from ocr.frames import sample_ocr_frames
from ocr.provider import OCRProvider
from ocr.tracking import build_text_tracks
from schemas.typography import (
    ColorObservation,
    NormalizedBBox,
    TextRegion,
    TypographyResult,
)


def _sample_color_from_region(
    image: np.ndarray,
    bbox: NormalizedBBox,
) -> ColorObservation:
    """从文字 bbox 附近简单采样主色与对比度。

    第一版不追求精确字体颜色，只做粗略分类。
    """
    h, w = image.shape[:2]
    x = int(bbox.x * w)
    y = int(bbox.y * h)
    bw = int(bbox.width * w)
    bh = int(bbox.height * h)

    # 扩大 20% 作为采样区
    margin_x = max(1, bw // 5)
    margin_y = max(1, bh // 5)
    x1 = max(0, x - margin_x)
    y1 = max(0, y - margin_y)
    x2 = min(w, x + bw + margin_x)
    y2 = min(h, y + bh + margin_y)

    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return ColorObservation(dominant_color="unknown", contrast_level="unknown")

    rgb = crop.reshape(-1, 3).astype(np.float32)
    mean = rgb.mean(axis=0)
    b, g, r = mean

    # 粗略颜色分类
    brightness = (r + g + b) / 3
    if brightness > 200:
        dominant = "white"
    elif brightness < 50:
        dominant = "black"
    elif r > g and r > b:
        dominant = "warm"
    elif b > r and b > g:
        dominant = "cool"
    else:
        dominant = "mixed"

    # 对比度：区域内颜色标准差相对均值
    std = rgb.std(axis=0).mean()
    contrast = (
        "high" if std > 60
        else "medium" if std > 30
        else "low"
    )

    return ColorObservation(
        dominant_color=dominant,
        contrast_level=contrast,
        notes=f"mean_rgb=({r:.0f},{g:.0f},{b:.0f}), std={std:.1f}",
    )


class ShotOCRAnalyzer:
    """负责单个 Shot 的 OCR + Typography 观察。"""

    def __init__(
        self,
        provider: OCRProvider,
        cache: OCRCache | None = None,
        target_fps: float = 6.0,
        min_frames: int = 3,
        max_frames: int = 12,
        max_long_edge: int = 960,
        strict_range: bool = False,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.target_fps = target_fps
        self.min_frames = min_frames
        self.max_frames = max_frames
        self.max_long_edge = max_long_edge
        self.strict_range = strict_range

    def analyze(
        self,
        video_path: Path,
        start: float,
        end: float,
    ) -> TypographyResult:
        """分析单个 Shot，返回 TypographyResult。"""
        started_at = time.time()
        result = TypographyResult()
        model_info = self.provider.get_model_info()
        if model_info.get("available") is False:
            result.analysis_error = model_info.get("error_message") or "OCR provider unavailable"
            return result

        sample_config = {
            "target_fps": self.target_fps,
            "min_frames": self.min_frames,
            "max_frames": self.max_frames,
            "max_long_edge": self.max_long_edge,
        }
        if self.strict_range:
            sample_config['sampling_strategy'] = 'selection-actual-pts-v2'
        model_info = self.provider.get_model_info()

        cached = None
        sampled_images: dict[float, np.ndarray] = {}
        if self.cache is not None:
            cached = self.cache.get(
                video_path,
                start,
                end,
                model_info,
                sample_config,
            )

        if cached is not None:
            frame_results = [
                {
                    "timestamp": f["timestamp"],
                    "regions": [TextRegion.model_validate(r) for r in f["regions"]],
                }
                for f in cached
            ]
        else:
            try:
                frames = sample_ocr_frames(
                    video_path,
                    start,
                    end,
                    target_fps=self.target_fps,
                    min_frames=self.min_frames,
                    max_frames=self.max_frames,
                    max_long_edge=self.max_long_edge,
                    strict_range=self.strict_range,
                )
            except Exception as exc:
                result.analysis_error = f"OCR 帧采样失败: {exc}"
                result.ocr_analysis_ms = int((time.time() - started_at) * 1000)
                return result

            frame_results = []
            for frame in frames:
                sampled_images[frame["timestamp"]] = frame["image"]
                regions = self.provider.analyze_frame(
                    frame["image"],
                    frame_timestamp=frame["timestamp"],
                    frame_width=frame["width"],
                    frame_height=frame["height"],
                )
                if self.strict_range:
                    # Native adapters may round timestamps; retain the decoded PTS clock.
                    for region in regions:
                        region.frame_timestamp = frame["timestamp"]
                frame_results.append({
                    "timestamp": frame["timestamp"],
                    "regions": regions,
                })

            if self.cache is not None:
                self.cache.set(
                    video_path,
                    start,
                    end,
                    model_info,
                    sample_config,
                    frame_results,
                )

        result.ocr_analysis_ms = int((time.time() - started_at) * 1000)

        # 所有区域汇总到 shot.text_regions（取每帧的代表）
        all_regions: list[TextRegion] = []
        for frame in frame_results:
            all_regions.extend(frame["regions"])
        result.text_regions = all_regions

        # 跨帧追踪
        tracks = build_text_tracks(frame_results)

        # Cache entries omit images; decode samples only for tracks needing color observations.
        if tracks and not sampled_images:
            try:
                sampled = sample_ocr_frames(
                    video_path,
                    start,
                    end,
                    target_fps=self.target_fps,
                    min_frames=self.min_frames,
                    max_frames=self.max_frames,
                    max_long_edge=self.max_long_edge,
                    strict_range=self.strict_range,
                )
                sampled_images = {frame["timestamp"]: frame["image"] for frame in sampled}
            except Exception:
                sampled_images = {}

        for track in tracks:
            region = max(track.regions, key=lambda r: r.confidence)
            image = sampled_images.get(region.frame_timestamp)
            if image is not None:
                track.color_observation = _sample_color_from_region(
                    image,
                    region.bbox_normalized,
                )

        result.typography_tracks = tracks
        result.has_text = len(tracks) > 0
        return result
