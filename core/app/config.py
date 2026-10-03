import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.runtime_paths import get_runtime_paths
from schemas.settings import OCRModelPaths


class AppConfig(BaseSettings):
    """应用配置，支持通过环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=None if __import__("os").environ.get("MRA_INSTANCE_ID") else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vision_provider: str = Field(
        default="mock",
        description="视觉分析 Provider: mock 或 qwen3-vl",
    )
    qwen_model_id: str = Field(
        default="qwen3-vl:4b",
        description="Qwen3-VL 模型标识",
    )
    qwen_api_base: str = Field(
        default="http://127.0.0.1:11434",
        description="Ollama 原生端点根路径（/api/chat；旧的 .../v1 会被自动归一化）",
    )
    qwen_api_key: str = Field(
        default="ollama",
        description="API Key（Ollama 通常不需要真实 key）",
    )
    vision_cache_dir: Path = Field(
        default=Path(__file__).parent.parent.parent / "output" / "vision_cache",
        description="Vision 分析缓存目录",
    )
    vision_timeout: float = Field(
        default=120.0,
        description="VLM 调用超时（秒）",
    )
    vision_max_retries: int = Field(
        default=1,
        description="VLM 调用失败后的最大重试次数",
    )
    cv_cache_dir: Path = Field(
        default=Path(__file__).parent.parent.parent / "output" / "cv_cache",
        description="CV 运动测量缓存目录",
    )
    cv_target_fps: float = Field(
        default=8.0,
        description="CV 分析目标采样帧率",
    )
    cv_max_long_edge: int = Field(
        default=720,
        description="CV 分析最长边分辨率",
    )

    # OCR & Typography (Milestone 4)
    auto_save_to_library: bool = True
    ocr_models: list[OCRModelPaths] = Field(default_factory=list)
    require_local_ocr_models: bool = True
    audio_cache_dir: Path = Path(__file__).parent.parent.parent / "output" / "audio_cache"
    audio_sample_rate: int = Field(default=22050, ge=8000, le=48000)
    audio_hop_length: int = Field(default=256, ge=64, le=2048)
    audio_max_duration: float = Field(default=1800, gt=0, le=7200)
    beat_sync_tolerance_ms: float = Field(default=80, ge=0, le=500)
    ocr_provider: str = Field(
        default="paddleocr",
        description="OCR 引擎：paddleocr 或 mock",
    )
    ocr_languages: list[str] = Field(
        default_factory=lambda: ["japan", "ch"],
        description="PaddleOCR 依次识别的语言模型列表",
    )
    ocr_target_fps: float = Field(
        default=6.0,
        description="OCR 帧采样目标帧率",
    )
    ocr_max_frames: int = Field(
        default=12,
        description="单个 Shot 最大 OCR 采样帧数",
    )
    ocr_min_frames: int = Field(
        default=3,
        description="单个 Shot 最小 OCR 采样帧数",
    )
    ocr_max_long_edge: int = Field(
        default=960,
        description="OCR 输入最长边分辨率",
    )
    ocr_confidence_threshold: float = Field(
        default=0.5,
        description="OCR 结果被纳入 Track 的最小置信度",
    )
    ocr_cache_dir: Path = Field(
        default=Path(__file__).parent.parent.parent / "output" / "ocr_cache",
        description="OCR 结果缓存目录",
    )
    typography_cache_dir: Path = Field(
        default=Path(__file__).parent.parent.parent / "output" / "typography_cache",
        description="Typography 语义分析缓存目录",
    )
    typography_max_tracks_per_shot: int = Field(
        default=5,
        description="每个 Shot 最多进行 Typography 语义分析的 Track 数",
    )
    typography_confidence_threshold: float = Field(
        default=0.5,
        description="Typography 语义分析触发阈值（Track 平均置信度）",
    )


_config: AppConfig | None = None


def get_config() -> AppConfig:
    """获取全局应用配置（单例）。"""
    global _config
    if _config is None:
        _config = AppConfig()
        paths = get_runtime_paths()
        if paths.settings.is_file() or os.environ.get("MRA_INSTANCE_ID"):
            from app.settings import SettingsStore

            settings = SettingsStore(paths).load()
            _config.qwen_api_base = settings.ollama_url
            _config.qwen_model_id = settings.qwen_model_id
            _config.ocr_models = settings.ocr_models
            _config.ocr_languages = [
                m.language for m in settings.ocr_models
            ] or _config.ocr_languages
            _config.beat_sync_tolerance_ms = settings.beat_sync_tolerance_ms
        if os.environ.get("MRA_INSTANCE_ID"):
            _config.vision_provider = "qwen3-vl"
            _config.ocr_provider = "paddleocr"
            _config.require_local_ocr_models = True
        if paths.data_root != Path(__file__).resolve().parents[2] / "output":
            for name in ["vision", "cv", "ocr", "typography", "audio"]:
                if f"{name.upper()}_CACHE_DIR" not in os.environ:
                    setattr(_config, f"{name}_cache_dir", paths.cache / name)
    return _config


def reset_config() -> None:
    """重置配置单例，主要用于测试。"""
    global _config
    _config = None
