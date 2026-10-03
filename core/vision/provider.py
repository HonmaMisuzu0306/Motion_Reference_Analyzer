from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from schemas.typography import TypographyAnalysis
from schemas.vision import VisionAnalysis


class ShotContext(BaseModel):
    """传递给 VisionProvider 的镜头上下文。"""

    shot_id: str
    start_time: float
    end_time: float
    frame_count: int
    video_filename: str = ""


class VisionProvider(ABC):
    """本地视觉语言模型统一接口。上层业务通过此接口调用具体模型实现。"""

    @abstractmethod
    def analyze_shot(
        self,
        images: list[Path],
        context: ShotContext,
    ) -> VisionAnalysis:
        """分析一组代表帧并返回结构化 VisionAnalysis。"""
        raise NotImplementedError

    def analyze_text_region(
        self,
        image_path: Path,
        crop_bbox: tuple[float, float, float, float],
        text: str,
        context: dict[str, Any],
    ) -> TypographyAnalysis:
        """分析单个文字区域（子图 + 上下文），返回 Typography 语义分析。

        默认不强制实现；未实现则返回 unknown。
        """
        return TypographyAnalysis()

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """返回当前模型信息，包括 provider 类型和模型标识。"""
        raise NotImplementedError

    def analyze_static_frame(self, image: Path, context: dict):
        from selection.static import StaticVisionAnalysis

        return StaticVisionAnalysis(analysis_error='当前视觉Provider尚不支持静态单帧分析')

    @property
    def supports_multi_image(self) -> bool:
        """是否原生支持一次输入多张图片。"""
        return True
