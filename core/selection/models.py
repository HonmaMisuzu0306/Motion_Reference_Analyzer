from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from selection.blend import MAX_SECONDS


class FrameIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_hash: str
    stream_index: int
    pts: int
    time_base_num: int
    time_base_den: int
    video_origin: float
    requested_time: float
    actual_time: float


@dataclass(frozen=True)
class ResolvedFrame:
    identity: FrameIdentity
    image: np.ndarray
    supports_sdr_blend: bool = True


def validate_range(start: float, end: float, duration: float) -> None:
    if not all(isfinite(t) for t in (start, end, duration)):
        raise ValueError('时间必须为有限数值')
    if not 0 <= start < end <= duration + 1e-7:
        raise ValueError('片段须满足 0 ≤ 入点 < 出点 ≤ 视频时长')
    if end - start > 60 + 1e-7:
        raise ValueError('片段最长为60秒')


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    kind: Literal['frame', 'clip']
    measurement: Literal['opacity_blend'] | None = None
    frame: FrameIdentity | None = None
    preview_token: str | None = None
    start: float | None = Field(default=None, allow_inf_nan=False)
    end: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def check_shape(self):
        if self.kind == 'frame':
            if self.measurement:
                raise ValueError('叠化测量需要视频选区')
            if self.frame is None or not self.preview_token or self.start is not None or self.end is not None:
                raise ValueError('单帧须先定位画面并提供预览身份')
        else:
            if self.start is None or self.end is None or self.frame is not None or self.preview_token is not None:
                raise ValueError('片段须提供入点、出点')
            validate_range(self.start, self.end, max(self.end, 0))
            if self.measurement and self.end - self.start > MAX_SECONDS:
                raise ValueError(f'叠化测量最长为{MAX_SECONDS}秒')
        return self


@dataclass(frozen=True)
class JobSnapshot:
    project_id: int
    source_path: Path
    source_hash: str
    request: SelectionRequest
    config: object
    record_id: str
    assets_dir: Path
    model_identity: str = ''
    display_geometry: tuple[int, int, float] | None = None
