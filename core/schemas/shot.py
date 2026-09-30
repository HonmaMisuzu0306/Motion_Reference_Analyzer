from typing import Any

from pydantic import BaseModel, Field


class TimeRange(BaseModel):
    start: float
    end: float
    duration: float


class VideoInfo(BaseModel):
    filename: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    bitrate: int = 0
    has_audio: bool = False


class Shot(BaseModel):
    shot_id: str = Field(..., description="镜头唯一标识")
    time: TimeRange
    frames: list[str] = Field(default_factory=list, description="代表帧文件名列表")
    observations: dict[str, Any] = Field(default_factory=dict)
    motion: dict[str, Any] = Field(default_factory=dict)
    typography: dict[str, Any] = Field(default_factory=dict)
    visual_effects: list[dict[str, Any]] = Field(default_factory=list)
    ae_hypothesis: dict[str, Any] = Field(default_factory=dict)
    ae_recipe: dict[str, Any] = Field(default_factory=dict)


class Project(BaseModel):
    project_name: str = "untitled"
    video: VideoInfo | None = None
    video_path: str | None = None
    shots: list[Shot] = Field(default_factory=list)
    analysis_status: str = "idle"
    analysis_message: str = ""
