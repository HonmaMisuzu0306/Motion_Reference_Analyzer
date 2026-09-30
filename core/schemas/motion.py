from pydantic import BaseModel, Field


class CameraMotion(BaseModel):
    type: str = Field(default="static", description="运动类型")
    strength: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str = ""


class RawMotion(BaseModel):
    translation_x: float = 0.0
    translation_y: float = 0.0
    scale_ratio: float = 1.0
    rotation_deg: float = 0.0
    confidence: float = 0.0
