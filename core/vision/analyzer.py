import logging
from pathlib import Path

from schemas.shot import Shot
from schemas.vision import VisionAnalysis
from vision.cache import VisionCache
from vision.mock import MockVisionProvider
from vision.prompts import PROMPT_VERSION
from vision.provider import ShotContext, VisionProvider

logger = logging.getLogger(__name__)


class ShotAnalyzer:
    """负责调用 VisionProvider 分析单个 Shot。"""

    def __init__(
        self,
        provider: VisionProvider | None = None,
        cache: VisionCache | None = None,
        max_retries: int = 1,
    ) -> None:
        self.provider = provider or MockVisionProvider()
        self.cache = cache
        self.max_retries = max_retries

    def _build_context(self, shot: Shot, video_filename: str = "") -> ShotContext:
        return ShotContext(
            shot_id=shot.shot_id,
            start_time=shot.time.start,
            end_time=shot.time.end,
            frame_count=len(shot.frames),
            video_filename=video_filename,
        )

    def _resolve_image_paths(self, shot: Shot, project_dir: Path) -> list[Path]:
        shot_dir = project_dir / "shots" / shot.shot_id
        return [shot_dir / name for name in shot.frames if name]

    def analyze(
        self,
        shot: Shot,
        project_dir: Path,
        video_filename: str = "",
    ) -> VisionAnalysis:
        """分析单个 Shot，优先读取缓存，必要时调用 VisionProvider。"""
        image_paths = self._resolve_image_paths(shot, project_dir)
        image_paths = [p for p in image_paths if p.exists()]

        if not image_paths:
            return VisionAnalysis(
                analysis_error=f"Shot {shot.shot_id} 没有可用的代表帧图片",
            )

        context = self._build_context(shot, video_filename)
        model_info = self.provider.get_model_info()
        model_id = model_info.get("model_id", "unknown")

        # 优先读取缓存
        if self.cache is not None:
            cached = self.cache.get(
                shot.shot_id,
                image_paths,
                model_id,
                PROMPT_VERSION,
                model_info=model_info,
            )
            if cached is not None:
                logger.info("Vision cache hit for shot %s", shot.shot_id)
                return cached

        # 调用 Provider，支持有限重试
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                result = self.provider.analyze_shot(image_paths, context)
                if result.analysis_error:
                    last_error = result.analysis_error
                    continue
                break
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Vision provider failed for shot %s (attempt %d): %s",
                    shot.shot_id,
                    attempt + 1,
                    exc,
                )
                result = VisionAnalysis(analysis_error=last_error)
        else:
            result = VisionAnalysis(
                analysis_error=f"Vision provider 重试耗尽: {last_error}",
            )

        # 写入缓存
        if self.cache is not None and not result.analysis_error:
            self.cache.set(
                shot.shot_id,
                image_paths,
                model_id,
                PROMPT_VERSION,
                result,
                model_info=model_info,
            )

        return result


def update_shot_with_analysis(
    shot: Shot,
    analysis: VisionAnalysis,
) -> None:
    """将 VisionAnalysis 写入 Shot 的对应字段。"""
    safe = analysis.model_dump_safe()
    shot.observations = safe.get("observations", {})
    shot.motion = safe.get("motion", {})
    shot.typography = safe.get("typography", {})
    shot.visual_effects = safe.get("visual_effects", [])
    shot.ae_hypothesis = safe.get("ae_hypothesis", {})
