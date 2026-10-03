from app.config import AppConfig
from vision.mock import MockVisionProvider
from vision.provider import VisionProvider
from vision.qwen import QwenVisionProvider


def create_vision_provider(config: AppConfig | None = None) -> VisionProvider:
    """根据配置创建对应的 VisionProvider 实例。"""
    cfg = config or AppConfig()

    provider = cfg.vision_provider.lower()
    if provider == "mock":
        return MockVisionProvider()

    if provider in {"qwen", "qwen3-vl", "qwen3vl"}:
        return QwenVisionProvider(
            model_id=cfg.qwen_model_id,
            api_base=cfg.qwen_api_base,
            api_key=cfg.qwen_api_key,
            timeout=cfg.vision_timeout,
        )

    raise ValueError(f"未知的 vision_provider: {cfg.vision_provider}")
