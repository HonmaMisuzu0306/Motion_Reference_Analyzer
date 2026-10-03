from pathlib import Path
from typing import Any

from schemas.typography import TypographyAnalysis
from schemas.vision import (
    AEHypothesis,
    Motion,
    Observation,
    Typography,
    VisionAnalysis,
    VisualEffect,
)
from vision.provider import ShotContext, VisionProvider


class MockVisionProvider(VisionProvider):
    """用于本地测试和 Pipeline 验证的 Mock Vision Provider。

    返回稳定、合法的结构化分析结果，不依赖真实模型。
    """

    def __init__(self, deterministic: bool = True) -> None:
        self._deterministic = deterministic

    def analyze_static_frame(self, image: Path, context: dict):
        from selection.static import StaticHypothesis, StaticObservation, StaticVisionAnalysis

        return StaticVisionAnalysis(
            observations=StaticObservation(subject_type='mixed', composition='测试Provider的静态示例'),
            ae_hypothesis=StaticHypothesis(layer_layout='测试布局，不代表实际识别结果'))

    def analyze_shot(
        self,
        images: list[Path],
        context: ShotContext,
    ) -> VisionAnalysis:
        """返回一个稳定的合法 VisionAnalysis。"""
        return VisionAnalysis(
            observations=Observation(
                subject_type="character",
                subject_position="center",
                background_type="illustration",
                depth_layers=2,
            ),
            motion=Motion(
                type="push_in",
                strength=0.2,
                confidence=0.8,
                description="画面主体略微放大，背景相对人物有轻微位移",
            ),
            typography=Typography(
                has_text=True,
                position="left",
                style="title",
            ),
            visual_effects=[
                VisualEffect(type="glow", confidence=0.65),
            ],
            ae_hypothesis=AEHypothesis(
                possible_method="2.5D parallax",
                possible_effect="Glow",
                possible_transition="Mask Reveal",
                notes="基于观察到的发光边缘和层间位移提出假设，不等于原作者工程",
            ),
        )

    def analyze_text_region(
        self,
        image_path: Path,
        crop_bbox: tuple[float, float, float, float],
        text: str,
        context: dict[str, Any],
    ) -> TypographyAnalysis:
        return TypographyAnalysis(
            role="lyrics",
            style_family="sans_serif",
            weight="regular",
            tracking="normal",
            alignment="center",
            orientation="horizontal",
            dominant_color="white",
            contrast_level="high",
            visual_emphasis="none",
            motion_style="static",
            confidence=0.75,
            observations=["Mock: 居中白色文字，无特殊装饰"],
            ae_hypothesis=["Mock: 可能使用 Text Layer + Opacity"],
        )

    def get_model_info(self) -> dict[str, Any]:
        return {
            "provider": "mock",
            "model_id": "mock-v1",
            "supports_multi_image": self.supports_multi_image,
            "deterministic": self._deterministic,
        }
