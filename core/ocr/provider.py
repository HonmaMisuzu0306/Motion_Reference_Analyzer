"""OCR Provider 抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np

from schemas.typography import TextRegion


class OCRProvider(ABC):
    """本地 OCR 引擎统一接口。"""

    @abstractmethod
    def analyze_frame(
        self,
        image: np.ndarray,
        frame_timestamp: float = 0.0,
        frame_width: int = 0,
        frame_height: int = 0,
    ) -> list[TextRegion]:
        """分析单帧，返回识别到的文字区域列表。"""
        raise NotImplementedError

    def analyze_frame_path(
        self,
        image_path: Path,
        frame_timestamp: float = 0.0,
    ) -> list[TextRegion]:
        """从图片路径读取后分析（便利方法）。"""
        from PIL import Image

        pil_image = Image.open(image_path).convert("RGB")
        image = np.array(pil_image)[:, :, ::-1].copy()
        return self.analyze_frame(
            image,
            frame_timestamp=frame_timestamp,
            frame_width=image.shape[1],
            frame_height=image.shape[0],
        )

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """返回 OCR 引擎与模型版本信息，用于缓存 Key。"""
        raise NotImplementedError


class MockOCRProvider(OCRProvider):
    """用于测试与降级场景的无操作 OCR Provider。"""

    def analyze_frame(
        self,
        image: np.ndarray,
        frame_timestamp: float = 0.0,
        frame_width: int = 0,
        frame_height: int = 0,
    ) -> list[TextRegion]:
        return []

    def get_model_info(self) -> dict[str, Any]:
        return {"provider": "mock", "version": "0.0.0"}
