from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class VisionProvider(ABC):
    """本地视觉语言模型统一接口。"""

    @abstractmethod
    def analyze_images(self, images: list[np.ndarray], prompt: str) -> dict[str, Any]:
        """分析一组图像并返回结构化 JSON。"""
        raise NotImplementedError

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """返回当前模型信息。"""
        raise NotImplementedError
