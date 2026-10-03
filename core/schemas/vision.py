from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SubjectType = Literal[
    "character",
    "object",
    "text",
    "mixed",
    "unknown",
]

SubjectPosition = Literal[
    "center",
    "left",
    "right",
    "top",
    "bottom",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "unknown",
]

BackgroundType = Literal[
    "solid",
    "photo",
    "illustration",
    "gradient",
    "complex",
    "unknown",
]

MotionType = Literal[
    "static",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "shake",
    "rotation",
    "complex",
    "unknown",
]

TextPosition = Literal[
    "left",
    "right",
    "center",
    "top",
    "bottom",
    "unknown",
]

TextStyle = Literal[
    "title",
    "lyrics",
    "character_name",
    "decorative",
    "narrative",
    "none",
    "unknown",
]

EffectType = Literal[
    "glow",
    "bloom",
    "blur",
    "chromatic_aberration",
    "noise",
    "grain",
    "vignette",
    "particles",
    "light_leak",
    "unknown",
]


class Observation(BaseModel):
    """从画面中直接观察到的视觉现象，不包含 AE 实现推测。"""

    subject_type: SubjectType = "unknown"
    subject_position: SubjectPosition = "unknown"
    background_type: BackgroundType = "unknown"
    depth_layers: int | None = Field(
        default=None,
        ge=1,
        description="画面感知到的空间层数，无法判断时返回 null",
    )

    @field_validator("subject_type", "subject_position", "background_type", mode="before")
    @classmethod
    def _coerce_blank_to_unknown(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "unknown"
        return value


class Motion(BaseModel):
    """镜头运动或画面运动趋势。"""

    type: MotionType = "unknown"
    strength: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_blank_to_unknown(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "unknown"
        return value


class Typography(BaseModel):
    """画面中的文字信息。"""

    has_text: bool = False
    position: TextPosition = "unknown"
    style: TextStyle = "unknown"

    @field_validator("position", "style", mode="before")
    @classmethod
    def _coerce_blank_to_unknown(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "unknown"
        return value


class VisualEffect(BaseModel):
    """观察到的视觉现象，作为 AE 效果推测的输入。"""

    type: EffectType = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_blank_to_unknown(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "unknown"
        return value


class AEHypothesis(BaseModel):
    """基于视觉观察对 AE 实现方式的假设，必须明确标注为假设。"""

    possible_method: str = "unknown"
    possible_effect: str = "unknown"
    possible_transition: str = "unknown"
    notes: str = ""


class VisionAnalysis(BaseModel):
    """单镜头视觉分析结果。"""

    observations: Observation = Field(default_factory=Observation)
    motion: Motion = Field(default_factory=Motion)
    typography: Typography = Field(default_factory=Typography)
    visual_effects: list[VisualEffect] = Field(default_factory=list)
    ae_hypothesis: AEHypothesis = Field(default_factory=AEHypothesis)
    analysis_error: str | None = None

    def model_dump_safe(self) -> dict[str, Any]:
        """返回兼容 Shot Schema 的字典，未知字段保留为 unknown/null。"""
        return self.model_dump(by_alias=False, exclude_none=False)
