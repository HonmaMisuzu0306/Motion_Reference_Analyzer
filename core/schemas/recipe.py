from typing import Any

from pydantic import BaseModel, Field


class LayerSuggestion(BaseModel):
    role: str
    suggestion: str


class CameraSuggestion(BaseModel):
    type: str = "static"
    strength: float = 0.0


class TransformSuggestion(BaseModel):
    key: str
    from_value: Any = None
    to_value: Any = None


class TypographySuggestion(BaseModel):
    method: str = ""
    duration: float = 0.0


class AERecipe(BaseModel):
    layers: list[LayerSuggestion] = Field(default_factory=list)
    camera: CameraSuggestion = Field(default_factory=CameraSuggestion)
    transform: dict[str, Any] = Field(default_factory=dict)
    typography: TypographySuggestion = Field(default_factory=TypographySuggestion)
    effects: list[str] = Field(default_factory=list)
    difficulty: dict[str, Any] = Field(default_factory=dict)
