from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MeasuredMotionStatus = Literal[
    "ok",
    "insufficient_features",
    "localized_support",
    "mixed_support",
    "too_few_valid_pairs",
    "high_variance",
    "incomplete_tracking",
    "failed",
]

MotionStrength = Literal["none", "very_light", "light", "medium", "strong"]


class FramePairTransform(BaseModel):
    """相邻帧对估计出的二维相似变换。"""

    model_config = ConfigDict(allow_inf_nan=False)

    start_time: float | None = Field(default=None, ge=0)
    end_time: float | None = Field(default=None, ge=0)
    valid: bool = False
    dx_px: float = 0.0
    dy_px: float = 0.0
    scale_ratio: float = 1.0
    rotation_deg: float = 0.0
    inlier_ratio: float = 0.0
    tracked_features: int = 0
    support_area_ratio: float | None = Field(default=None, ge=0, le=1)


class MotionSample(BaseModel):
    """Source-relative presentation time and transform from this segment's first frame."""
    model_config = ConfigDict(allow_inf_nan=False)

    source_time: float = Field(ge=0)
    segment_id: int = Field(ge=0)
    segment_start_time: float = Field(ge=0)
    translation_x_px: float = 0.0
    translation_y_px: float = 0.0
    translation_x_ratio: float = 0.0
    translation_y_ratio: float = 0.0
    scale_ratio: float = Field(default=1.0, gt=0)
    rotation_deg: float = 0.0
    # Original-pixel coordinates, mapping the segment reference frame to this frame.
    matrix: tuple[tuple[float, float, float], tuple[float, float, float]]


class MeasuredMotion(BaseModel):
    """基于 OpenCV 客观测量的镜头全局运动。

    仅描述画面可测量的全局几何变化，不推断 AE 实现方式。
    """

    model_config = ConfigDict(allow_inf_nan=False)

    status: MeasuredMotionStatus = "ok"
    method: str = "feature_tracking_affine"
    message: str = ""

    frame_width: int = Field(default=0, ge=0)
    frame_height: int = Field(default=0, ge=0)
    translation_reference: Literal['legacy_top_left', 'frame_center'] = 'legacy_top_left'
    trajectory_status: Literal['not_measured', 'complete', 'partial'] = 'not_measured'
    trajectory: list[MotionSample] = Field(default_factory=list)

    # Target grid of the retained measurement; actual sample times follow source PTS.
    sampling_target_fps: float | None = Field(default=None, gt=0)
    sample_count: int = 0
    valid_pair_count: int = 0
    long_baseline_check_count: int = Field(default=0, ge=0)
    long_baseline_conflict_count: int = Field(default=0, ge=0)
    mixed_support_pair_count: int = Field(default=0, ge=0)
    spatially_limited_pair_count: int = Field(default=0, ge=0)
    total_pair_count: int = 0

    translation_x_px: float = 0.0
    translation_y_px: float = 0.0
    translation_x_ratio: float = 0.0
    translation_y_ratio: float = 0.0

    scale_ratio: float = 1.0
    scale_change_percent: float = 0.0

    rotation_deg: float = 0.0

    motion_strength: MotionStrength = "none"
    stability: float = Field(default=0.0, ge=0.0, le=1.0)
    shake_score: float = Field(default=0.0, ge=0.0, le=1.0)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    pairs: list[FramePairTransform] = Field(default_factory=list)
    cv_analysis_ms: int = 0

    def model_dump_safe(self) -> dict:
        return self.model_dump(by_alias=False, exclude_none=False)
