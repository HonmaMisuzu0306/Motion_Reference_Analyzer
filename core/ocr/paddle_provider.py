from typing import Any


class PaddleOCRProvider:
    """PaddleOCR 接入占位实现。"""

    def __init__(self) -> None:
        self.engine = None

    def recognize(self, image_path: str) -> list[dict[str, Any]]:
        return []
