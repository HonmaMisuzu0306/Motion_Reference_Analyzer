from typing import Literal

from pydantic import BaseModel, Field

MeasuredMotionStatus = Literal[
    "ok",
    "insufficient_features",
    "too_few_valid_pairs",
    "high_variance",
    "failed",
]

MotionStrength = Literal["none", "very_light", "light", "medium", "strong"]


class FramePairTransform(BaseModel):
    """相邻帧对估计出的二维相似变换。"""

    dx_px: float = 0.0
    dy_px: float = 0.0
    scale_ratio: float = 1.0
    rotation_deg: float = 0.0
    inlier_ratio: float = 0.0
    tracked_features: int = 0


class MeasuredMotion(BaseModel):
    """基于 OpenCV 客观测量的镜头全局运动。

    仅描述画面可测量的全局几何变化，不推断 AE 实现方式。
    """

    status: MeasuredMotionStatus = "ok"
    method: str = "feature_tracking_affine"
    message: str = ""

    sample_count: int = 0
    valid_pair_count: int = 0
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
