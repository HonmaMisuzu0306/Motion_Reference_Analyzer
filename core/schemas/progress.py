"""分析进度结构化状态。

进度来自后端 Pipeline 的真实状态更新，禁止前端使用定时器伪造。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StageStatus = Literal["pending", "running", "completed", "error", "skipped"]
StageKey = Literal[
    "preparing",
    "scene_detect",
    "extract_frames",
    "audio_analysis",
    "vision_analysis",
    "cv_analysis",
    "ocr_analysis",
    "typography_analysis",
    "recipe_generation",
    "saving",
    "done",
]

STAGE_WEIGHTS: dict[StageKey, float] = {
    "preparing": 0.03,
    "scene_detect": 0.10,
    "extract_frames": 0.10,
    "audio_analysis": 0.05,
    "vision_analysis": 0.23,
    "cv_analysis": 0.15,
    "ocr_analysis": 0.12,
    "typography_analysis": 0.14,
    "recipe_generation": 0.05,
    "saving": 0.03,
    "done": 0.00,
}


def default_stage_keys() -> list[StageKey]:
    """返回所有预定义 Stage 键（不含 done，done 仅用于顶层状态）。"""
    return [
        "preparing",
        "scene_detect",
        "extract_frames",
        "audio_analysis",
        "vision_analysis",
        "cv_analysis",
        "ocr_analysis",
        "typography_analysis",
        "recipe_generation",
        "saving",
    ]


class StageProgress(BaseModel):
    """单个 Stage 的进度。"""

    status: StageStatus = "pending"
    progress: float = Field(0.0, ge=0.0, le=1.0)
    completed: int = Field(0, ge=0)
    total: int = Field(0, ge=0)
    failed: int = Field(0, ge=0)
    message: str = ""


class AnalysisProgress(BaseModel):
    """整个分析 Pipeline 的进度状态。"""

    status: str = "idle"
    stage: str = "idle"
    overall_progress: float = Field(0.0, ge=0.0, le=1.0)
    message: str = ""
    current_shot: int | None = None
    total_shots: int | None = None
    started_at: float | None = None
    completed_at: float | None = None
    eta_seconds: float | None = None
    error: dict[str, str] | None = None
    stages: dict[str, StageProgress] = Field(
        default_factory=lambda: {key: StageProgress() for key in default_stage_keys()},
    )

    def model_dump_safe(self) -> dict:
        """返回可安全序列化的字典。"""
        return self.model_dump(mode="json")
