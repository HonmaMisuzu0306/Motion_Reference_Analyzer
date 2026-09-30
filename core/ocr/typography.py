from typing import Any


def classify_text_usage(text: str, bbox: list[int]) -> dict[str, Any]:
    """根据文字内容与位置判断用途。"""
    return {
        "text": text,
        "bbox": bbox,
        "purpose": "unknown",
        "dynamic": False,
    }
