"""Typography 语义分析（复用 Qwen3-VL）。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from ocr.typography_prompts import PROMPT_VERSION
from schemas.typography import TextTrack, TypographyAnalysis
from vision.provider import VisionProvider

logger = logging.getLogger(__name__)

class TypographyCache:
    """Typography 语义分析缓存。"""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(
        self,
        image_path: Path,
        bbox: tuple[float, float, float, float],
        text: str,
        model_info: dict[str, Any],
    ) -> str:
        stat = image_path.stat() if image_path.exists() else None
        size = stat.st_size if stat else 0
        mtime = stat.st_mtime_ns if stat else 0
        raw = json.dumps({
            "path": str(image_path),
            "size": size,
            "mtime": mtime,
            "bbox": bbox,
            "text": text,
            "model_info": model_info,
            "prompt_version": PROMPT_VERSION,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        image_path: Path,
        bbox: tuple[float, float, float, float],
        text: str,
        model_info: dict[str, Any],
    ) -> TypographyAnalysis | None:
        key = self._make_key(image_path, bbox, text, model_info)
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            analysis = TypographyAnalysis.model_validate(data)
            return None if analysis.analysis_error else analysis
        except Exception:
            return None

    def set(
        self,
        image_path: Path,
        bbox: tuple[float, float, float, float],
        text: str,
        model_info: dict[str, Any],
        analysis: TypographyAnalysis,
    ) -> Path:
        key = self._make_key(image_path, bbox, text, model_info)
        path = self._cache_path(key)
        path.write_text(
            json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


class TypographySemanticAnalyzer:
    """对 TextTrack 进行 Typography 语义分析。"""

    def __init__(
        self,
        provider: VisionProvider,
        cache: TypographyCache | None = None,
        max_tracks_per_shot: int = 5,
        confidence_threshold: float = 0.5,
        max_retries: int = 1,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.max_tracks_per_shot = max_tracks_per_shot
        self.confidence_threshold = confidence_threshold
        self.max_retries = max_retries

    def analyze_tracks(
        self,
        tracks: list[TextTrack],
        image_path: Path,
        shot_id: str,
        video_path: Path | None = None,
    ) -> tuple[list[TextTrack], int]:
        """对 tracks 进行 Typography 语义分析，返回更新后的 tracks 与耗时。"""
        started_at = time.time()
        model_info = self.provider.get_model_info()

        # 优先分析置信度高、时间长的 track；最多分析 max_tracks_per_shot 个
        candidate_tracks = [
            t for t in tracks
            if t.average_confidence >= self.confidence_threshold
        ]
        candidate_tracks.sort(key=lambda t: (t.average_confidence, t.duration), reverse=True)
        candidate_tracks = candidate_tracks[: self.max_tracks_per_shot]

        for track in candidate_tracks:
            track_image = image_path
            region = max(track.regions, key=lambda r: r.confidence) if track.regions else None
            sample_bbox = track.average_bbox
            if video_path is not None and region is not None:
                # The shot's first representative frame may not contain this text.
                from PIL import Image

                from video.frame_sampler import sample_frames
                timestamp = region.frame_timestamp
                decoded = sample_frames(video_path, timestamp, timestamp, count=1)[0]['image']
                track_image = image_path.parent / f'text_{timestamp:.3f}.jpg'
                if not track_image.exists():
                    Image.fromarray(decoded[:, :, ::-1]).save(track_image, quality=90)
                sample_bbox = region.bbox_normalized
            bbox = (
                sample_bbox.x,
                sample_bbox.y,
                sample_bbox.width,
                sample_bbox.height,
            )
            text = track.canonical_text or track.regions[0].text if track.regions else ""

            cached = None
            if self.cache is not None:
                cached = self.cache.get(track_image, bbox, text, model_info)

            if cached is not None:
                track.typography_analysis = cached
                continue

            analysis: TypographyAnalysis | None = None
            context = {"shot_id": shot_id, "timestamp": track.start_time}
            last_error = ""
            for attempt in range(self.max_retries + 1):
                try:
                    analysis = self.provider.analyze_text_region(
                        track_image,
                        bbox,
                        text,
                        context,
                    )
                    if analysis.analysis_error:
                        last_error = analysis.analysis_error
                        logger.warning("Typography analysis failed for %s (attempt %d): %s",
                                       track.track_id, attempt + 1, last_error)
                        continue
                    break
                except Exception as exc:
                    last_error = str(exc)
                    analysis = None
                    logger.warning(
                        "Typography analysis failed for %s (attempt %d): %s",
                        track.track_id,
                        attempt + 1,
                        exc,
                    )
            if analysis is None:
                analysis = TypographyAnalysis(
                    observations=[f"Typography 分析失败: {last_error}"],
                    analysis_error=last_error or "Typography 分析失败",
                )

            if self.cache is not None and not analysis.analysis_error and analysis.confidence > 0:
                self.cache.set(track_image, bbox, text, model_info, analysis)

            track.typography_analysis = analysis

        elapsed_ms = int((time.time() - started_at) * 1000)
        return tracks, elapsed_ms
