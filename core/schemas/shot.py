from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator

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
    frame_timestamps: list[Annotated[float, Field(ge=0, allow_inf_nan=False)]] = Field(
        default_factory=list, description="与 frames 一一对应的实际源视频秒；旧记录为空")
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

    @model_validator(mode='before')
    @classmethod
    def restore_representative_times(cls, value):
        if isinstance(value, dict) and not value.get('frame_timestamps'):
            versions = value.get('provider_versions') or {}
            metadata = versions.get('representative_frames') or {}
            if isinstance(metadata, dict) and metadata.get('timestamps'):
                value = {**value, 'frame_timestamps': metadata['timestamps']}
        return value

    @model_validator(mode='after')
    def preserve_representative_times(self):
        if self.frame_timestamps:
            if len(self.frame_timestamps) != len(self.frames):
                raise ValueError('代表帧时间必须与文件一一对应')
            if any(a >= b for a, b in zip(self.frame_timestamps, self.frame_timestamps[1:])):
                raise ValueError('代表帧实际时间必须严格递增')
            if any(not self.time.start <= timestamp < self.time.end for timestamp in self.frame_timestamps):
                raise ValueError('代表帧时间必须处于镜头半开区间内')
            metadata = self.provider_versions.get('representative_frames') or {}
            self.provider_versions = {**self.provider_versions, 'representative_frames': {
                'strategy': 'actual-pts', **metadata,
                'time_origin': 'source_video_seconds', 'timestamps': list(self.frame_timestamps),
            }}
        return self


class Project(BaseModel):
    project_name: str = "untitled"
    display_name: str = ""
    video: VideoInfo | None = None
    video_path: str | None = None
    source_hash: str = ""
    assets_dir: str | None = None
    shots: list[Shot] = Field(default_factory=list)
    audio: AudioAnalysis = Field(default_factory=AudioAnalysis)
    rhythm_summary: RhythmSummary = Field(default_factory=RhythmSummary)
    analysis_status: str = "idle"
    analysis_message: str = ""
    library_warning: str = ""
    library_project_id: int | None = None
    progress: AnalysisProgress = Field(default_factory=AnalysisProgress)
