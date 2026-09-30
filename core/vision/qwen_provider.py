from typing import Any

import numpy as np

from .provider import VisionProvider


class QwenVLProvider(VisionProvider):
    """Qwen3-VL 本地模型接入占位实现。"""

    def __init__(self, model_id: str = "Qwen3-VL-2B") -> None:
        self.model_id = model_id
        self.loaded = False

    def analyze_images(self, images: list[np.ndarray], prompt: str) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "prompt": prompt,
            "result": {
                "composition": {},
                "motion": {},
                "typography": {},
                "visual_effects": [],
                "ae_hypothesis": {},
                "confidence": 0.0,
            },
        }

    def get_model_info(self) -> dict[str, Any]:
        return {
            "provider": "qwen-vl",
            "model_id": self.model_id,
            "loaded": self.loaded,
        }
