"""Measured audio events on the video clock; beat sync is a tolerance, not intent."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AudioPoint(BaseModel):
    time: float = Field(ge=0, allow_inf_nan=False)
    rms: float = Field(ge=0, allow_inf_nan=False)


class AudioAnalysis(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    status: Literal['pending', 'ok', 'no_audio', 'silent', 'insufficient', 'error'] = 'pending'
    message: str = ''
    method: str = 'librosa-beat-onset-v2-video-clock'
    library_version: str = ''
    sample_rate: int = 22050
    hop_length: int = 256
    duration: float = Field(default=0, ge=0)
    audio_start: float = 0
    video_origin: float = 0
    stream_index: int | None = None
    tempo_bpm: float | None = Field(default=None, gt=0)
    beat_times: list[float] = Field(default_factory=list)
    onset_times: list[float] = Field(default_factory=list)
    beat_regularity: float = Field(default=0, ge=0, le=1,
                                 description='Inter-beat regularity heuristic, not probability')
    waveform: list[AudioPoint] = Field(default_factory=list)
    cache_hit: bool = False


class CutRhythm(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    status: Literal['not_analyzed', 'not_cut', 'ok', 'no_beats', 'unavailable'] = 'not_analyzed'
    cut_time: float | None = None
    nearest_beat: float | None = None
    delta_ms: float | None = None
    beat_sync: bool | None = None
    nearest_onset: float | None = None
    onset_delta_ms: float | None = None
    tolerance_ms: float = Field(default=80, ge=0, le=500)
    message: str = ''


class RhythmSummary(BaseModel):
    cut_count: int = 0
    measured_cut_count: int = 0
    synced_cut_count: int = 0
    sync_ratio: float | None = None
    median_abs_delta_ms: float | None = None
    tolerance_ms: float = 80
    excluded_shot_count: int = 0
