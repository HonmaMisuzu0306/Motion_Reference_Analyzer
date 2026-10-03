from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class OCRModelPaths(BaseModel):
    language: str = "ch"
    detection_dir: Path
    recognition_dir: Path
    orientation_dir: Path | None = None


class UserSettings(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    ollama_url: str = "http://127.0.0.1:11434"
    qwen_model_id: str = Field(default="qwen3-vl:4b", min_length=1, max_length=128)
    ocr_models: list[OCRModelPaths] = Field(default_factory=list)
    beat_sync_tolerance_ms: float = Field(default=80, ge=0, le=500)

    @field_validator("ollama_url")
    @classmethod
    def local_service(cls, value):
        u = urlparse(value)
        if (
            u.scheme != "http"
            or u.hostname not in {"127.0.0.1", "localhost", "::1"}
            or u.username
            or u.password
            or u.query
            or u.fragment
        ):
            raise ValueError("仅支持本机 Ollama HTTP 服务地址")
        return value.rstrip("/")
