"""Typography / OCR 结构化 Schema。

所有字段区分：
- Observation：从画面中直接观察到的现象
- Hypothesis：对 AE 实现方式的推测
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Orientation = Literal["horizontal", "vertical", "unknown"]
LanguageHint = Literal["ja", "en", "zh", "mixed", "unknown"]

TextRole = Literal[
    "title",
    "subtitle",
    "character_name",
    "lyrics",
    "dialogue",
    "credit",
    "narrative",
    "decorative",
    "logo_like",
    "unknown",
]

StyleFamily = Literal[
    "serif",
    "sans_serif",
    "display",
    "handwritten_like",
    "decorative",
    "unknown",
]

WeightImpression = Literal["thin", "regular", "medium", "bold", "unknown"]
TrackingImpression = Literal["tight", "normal", "wide", "unknown"]
Alignment = Literal["left", "center", "right", "top", "bottom", "unknown"]
ContrastLevel = Literal["high", "medium", "low", "unknown"]
DominantColor = Literal[
    "white",
    "black",
    "red",
    "blue",
    "warm",
    "cool",
    "mixed",
    "unknown",
]
VisualEmphasis = Literal[
    "glow",
    "outline",
    "shadow",
    "blur",
    "stroke",
    "none",
    "unknown",
]

TextMotion = Literal[
    "static",
    "slide_left",
    "slide_right",
    "slide_up",
    "slide_down",
    "scale_in",
    "scale_out",
    "unknown",
]

Appearance = Literal[
    "hard_cut",
    "fade",
    "slide",
    "scale",
    "mask_like_reveal",
    "unknown",
]


class BBox(BaseModel):
    """像素级边界框。"""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class NormalizedBBox(BaseModel):
    """归一化边界框（0.0 ~ 1.0）。"""

    x: float = Field(0.0, ge=0.0, le=1.0)
    y: float = Field(0.0, ge=0.0, le=1.0)
    width: float = Field(0.0, ge=0.0, le=1.0)
    height: float = Field(0.0, ge=0.0, le=1.0)


class TextRegion(BaseModel):
    """单帧 OCR 识别出的一个文字区域。"""

    id: str = Field(default="", description="帧内唯一标识")
    text: str = ""
    normalized_text: str = ""
    language: LanguageHint = "unknown"
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    bbox_px: BBox = Field(default_factory=BBox)
    bbox_normalized: NormalizedBBox = Field(default_factory=NormalizedBBox)

    center_x: float = Field(0.0, ge=0.0, le=1.0)
    center_y: float = Field(0.0, ge=0.0, le=1.0)
    width_ratio: float = Field(0.0, ge=0.0, le=1.0)
    height_ratio: float = Field(0.0, ge=0.0, le=1.0)

    orientation: Orientation = "horizontal"
    frame_timestamp: float = 0.0


class ColorObservation(BaseModel):
    """从文字区域附近直接采样/观察到的颜色信息。"""

    dominant_color: DominantColor = "unknown"
    contrast_level: ContrastLevel = "unknown"
    notes: str = ""


class TypographyAnalysis(BaseModel):
    """对单个文字区域/Track 的语义与视觉分析。"""

    role: TextRole = "unknown"
    style_family: StyleFamily = "unknown"
    weight: WeightImpression = "unknown"
    tracking: TrackingImpression = "unknown"
    alignment: Alignment = "unknown"
    orientation: Orientation = "unknown"
    dominant_color: DominantColor = "unknown"
    contrast_level: ContrastLevel = "unknown"
    visual_emphasis: VisualEmphasis = "unknown"
    motion_style: str = "unknown"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    observations: list[str] = Field(default_factory=list)
    ae_hypothesis: list[str] = Field(default_factory=list)
    analysis_error: str | None = None

    @field_validator(
        "role",
        "style_family",
        "weight",
        "tracking",
        "alignment",
        "orientation",
        "dominant_color",
        "contrast_level",
        "visual_emphasis",
        mode="before",
    )
    @classmethod
    def _coerce_blank_to_unknown(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "unknown"
        return value


class TextTrack(BaseModel):
    """跨帧追踪后的文字轨道。"""

    track_id: str = ""
    canonical_text: str = ""
    language: LanguageHint = "unknown"

    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0

    average_confidence: float = Field(0.0, ge=0.0, le=1.0)
    average_bbox: NormalizedBBox = Field(default_factory=NormalizedBBox)
    frame_count: int = 0

    regions: list[TextRegion] = Field(default_factory=list)

    movement: TextMotion = "unknown"
    appearance: Appearance = "unknown"
    timing_notes: str = ""
    observed_notes: list[str] = Field(default_factory=list)
    ae_hypothesis: list[str] = Field(default_factory=list)

    color_observation: ColorObservation = Field(default_factory=ColorObservation)
    typography_analysis: TypographyAnalysis | None = None

    def model_dump_safe(self) -> dict[str, Any]:
        """返回可安全 JSON 序列化的字典。"""
        return self.model_dump(by_alias=False, exclude_none=False)


class TypographyResult(BaseModel):
    """单 Shot 的完整 Typography 分析结果。"""

    text_regions: list[TextRegion] = Field(default_factory=list)
    typography_tracks: list[TextTrack] = Field(default_factory=list)
    has_text: bool = False
    analysis_error: str | None = None
    ocr_analysis_ms: int = 0
    typography_analysis_ms: int = 0
