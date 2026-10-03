from typing import Any

from pydantic import BaseModel, Field

from schemas.audio import AudioAnalysis, CutRhythm, RhythmSummary
from schemas.measured_motion import MeasuredMotion
from schemas.progress import AnalysisProgress
from schemas.typography import TextRegion, TextTrack


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
    library_id: int | None = Field(default=None, description="已载入的 Library 记录 ID")
    time: TimeRange
    frames: list[str] = Field(default_factory=list, description="代表帧文件名列表")
    observations: dict[str, Any] = Field(default_factory=dict)
    motion: dict[str, Any] = Field(default_factory=dict)
    typography: dict[str, Any] = Field(default_factory=dict)
    visual_effects: list[dict[str, Any]] = Field(default_factory=list)
    ae_hypothesis: dict[str, Any] = Field(default_factory=dict)
    ae_recipe: dict[str, Any] = Field(default_factory=dict)
    measured_motion: MeasuredMotion = Field(default_factory=MeasuredMotion)
    motion_summary: dict[str, Any] = Field(default_factory=dict)
    rhythm: CutRhythm = Field(default_factory=CutRhythm)
    analysis_version: str = "mra-analysis-v1"
    pipeline_version: str = "mra-pipeline-v1"
    provider_versions: dict[str, Any] = Field(default_factory=dict)

    # Milestone 4: OCR & Typography
    text_regions: list[TextRegion] = Field(default_factory=list)
    typography_tracks: list[TextTrack] = Field(default_factory=list)

    analysis_error: str = Field(
        default="",
        description="单 Shot 分析过程中的错误信息；Pipeline 不应因单个 Shot 失败而整体中止",
    )


class Project(BaseModel):
    project_name: str = "untitled"
    display_name: str = ""
    video: VideoInfo | None = None
    video_path: str | None = None
    assets_dir: str | None = None
    shots: list[Shot] = Field(default_factory=list)
    audio: AudioAnalysis = Field(default_factory=AudioAnalysis)
    rhythm_summary: RhythmSummary = Field(default_factory=RhythmSummary)
    analysis_status: str = "idle"
    analysis_message: str = ""
    library_warning: str = ""
    library_project_id: int | None = None
    progress: AnalysisProgress = Field(default_factory=AnalysisProgress)
