"""A static schema cannot express camera motion, transitions or text animation."""
from pydantic import BaseModel, Field

from schemas.vision import Observation, Typography, VisualEffect

STATIC_PROMPT_VERSION = 'static-frame-zh-v1'


class StaticObservation(Observation):
    composition: str = ''
    color_description: str = ''


class StaticHypothesis(BaseModel):
    layer_layout: str = ''
    color_treatment: str = ''
    visible_effects: str = ''
    notes: str = ''


class StaticVisionAnalysis(BaseModel):
    observations: StaticObservation = Field(default_factory=StaticObservation)
    typography: Typography = Field(default_factory=Typography)
    visual_effects: list[VisualEffect] = Field(default_factory=list)
    ae_hypothesis: StaticHypothesis = Field(default_factory=StaticHypothesis)
    analysis_error: str = ''


def static_recipe(analysis: StaticVisionAnalysis, regions: list) -> dict:
    return {
        'basis': '仅由单张画面提出的静态复现假设，不代表作者工程',
        'layer_layout': analysis.ae_hypothesis.layer_layout,
        'color_treatment': analysis.ae_hypothesis.color_treatment,
        'visible_effects': analysis.ae_hypothesis.visible_effects,
        'text_layers': [{'text': r.text, 'bbox': r.bbox_normalized.model_dump()} for r in regions],
        'camera': {'status': 'not_applicable', 'reason': '单帧无法确定运动'},
        'animation': {'status': 'not_applicable', 'reason': '单帧无法确定动画和转场'},
    }
