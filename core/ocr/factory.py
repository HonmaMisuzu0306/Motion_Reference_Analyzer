"""OCR Provider 工厂。"""

from __future__ import annotations

from app.config import AppConfig
from ocr.paddle_provider import PaddleOCRProvider
from ocr.provider import MockOCRProvider, OCRProvider


def create_ocr_provider(config: AppConfig) -> OCRProvider:
    """根据配置创建 OCR Provider。"""
    if config.ocr_provider == "paddleocr":
        return PaddleOCRProvider(languages=config.ocr_languages,model_paths=config.ocr_models if config.require_local_ocr_models else None)
    return MockOCRProvider()
