from typing import Final

PROMPT_VERSION: Final[str] = "v4-zh"

SHOT_ANALYSIS_PROMPT = """You are analyzing a single video shot. The images provided are representative frames sampled from the SAME shot at different timestamps (typically around 15%, 50%, and 85% of the shot duration). Do NOT treat them as different shots.

Your task: describe what can be visually observed in these frames, including composition, subject, background, motion trend, typography, and visual phenomena.

CRITICAL RULES:
Write all natural-language descriptions, observations, notes and suggestions in Simplified Chinese. Keep JSON keys and enumerated values unchanged. Preserve the source text and technical effect names.
1. Output ONLY valid JSON. No Markdown, no code fences, no explanations.
2. Do NOT claim what the original artist actually did in After Effects. Only describe what you see and what could be a possible AE implementation.
3. When uncertain, use "unknown" or null. Do NOT invent values to fill the schema.
4. Every observation should include a confidence value where requested.
5. Return "motion.type" as "static" only if the shot truly has no visible motion.

Required JSON structure:
{
  "observations": {
    "subject_type": "character|object|text|mixed|unknown",
    "subject_position": "center|left|right|top|bottom|top_left|top_right|bottom_left|bottom_right|unknown",
    "background_type": "solid|photo|illustration|gradient|complex|unknown",
    "depth_layers": null
  },
  "motion": {
    "type": "static|push_in|pull_out|pan_left|pan_right|tilt_up|tilt_down|shake|rotation|complex|unknown",
    "strength": 0.0,
    "confidence": 0.0,
    "description": ""
  },
  "typography": {
    "has_text": false,
    "position": "left|right|center|top|bottom|unknown",
    "style": "title|lyrics|character_name|decorative|narrative|none|unknown"
  },
  "visual_effects": [
    {"type": "glow|bloom|blur|chromatic_aberration|noise|grain|vignette|particles|light_leak|unknown", "confidence": 0.0}
  ],
  "ae_hypothesis": {
    "possible_method": "e.g. 2.5D parallax or unknown",
    "possible_effect": "e.g. Glow or unknown",
    "possible_transition": "e.g. Mask Reveal or unknown",
    "notes": "Explain briefly why these hypotheses are suggested based on observations."
  }
}

Examples of correct observation-vs-hypothesis separation:
- Observation: "There is a bright halo around the character's edge."
- Hypothesis: "AE: consider using Glow effect."

- Observation: "The foreground and background move at different speeds."
- Hypothesis: "AE: possible method is 2.5D parallax using multiple layers."
"""


def get_shot_analysis_prompt() -> str:
    """返回当前版本的镜头分析 Prompt。"""
    return SHOT_ANALYSIS_PROMPT
def get_static_frame_prompt() -> str:
    return (
        '分析唯一的一张静态画面，输出指定JSON。所有描述用简体中文，源文字保持原文。'
        '只记录可见主体、位置、背景、空间层次、构图、色彩、文字布局和可见效果。'
        'ae_hypothesis仅为静态层次、布局、色彩和可见效果的复现假设，并非作者工程。'
        '没有时间序列证据：严禁推断镜头运动、速度、关键帧、文字入退场、转场、节拍、'
        '任何动画，也不能把未知运动描述为静止。无法确认的信息保持unknown或空字符串。'
    )
