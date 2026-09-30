from pydantic import BaseModel, Field


class TextRegion(BaseModel):
    text: str
    bbox: list[int] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Typography(BaseModel):
    has_text: bool = False
    regions: list[TextRegion] = Field(default_factory=list)
    purpose: str = "none"
    dynamic: bool = False
