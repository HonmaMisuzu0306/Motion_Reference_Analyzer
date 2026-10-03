from typing import Final

PROMPT_VERSION: Final[str] = "v4-zh"

TYPOGRAPHY_ANALYSIS_PROMPT = """You are analyzing a cropped text region from a video frame.
Your task is to describe the typography visually, WITHOUT guessing the exact font name or the original After Effects project.

CRITICAL RULES:
Write all natural-language observations and suggestions in Simplified Chinese. Keep JSON keys and enumerated values unchanged. Preserve the source text and technical effect names.
1. Output ONLY valid JSON. No Markdown, no code fences, no explanations.
2. Do NOT claim what the original artist did in After Effects. Only describe what you see and what could be a possible AE implementation.
3. Do NOT guess exact font names (e.g. "Source Han Sans", "Futura"). Only use the visual categories below.
4. When uncertain, use "unknown". Do NOT invent values to fill the schema.
5. Every classification should include a confidence value.

Context: this crop is from a video shot. The full text in this region is: "{text}".

Required JSON structure:
{
  "role": "title|subtitle|character_name|lyrics|dialogue|credit|narrative|decorative|logo_like|unknown",
  "style_family": "serif|sans_serif|display|handwritten_like|decorative|unknown",
  "weight": "thin|regular|medium|bold|unknown",
  "tracking": "tight|normal|wide|unknown",
  "alignment": "left|center|right|top|bottom|unknown",
  "orientation": "horizontal|vertical|unknown",
  "dominant_color": "white|black|red|blue|warm|cool|mixed|unknown",
  "contrast_level": "high|medium|low|unknown",
  "visual_emphasis": "glow|outline|shadow|blur|stroke|none|unknown",
  "motion_style": "static|slide_left|slide_right|slide_up|slide_down|scale_in|scale_out|fade|unknown",
  "confidence": 0.0,
  "observations": [
    "Describe what you actually see, e.g. white thin sans-serif text centered in the frame."
  ],
  "ae_hypothesis": [
    "Possible AE implementation, e.g. Text Animator with Tracking + Opacity."
  ]
}

Examples of observation-vs-hypothesis separation:
- Observation: "The text is centered, thin, and white against a dark background."
- Hypothesis: "AE: consider a centered Text Layer with a simple Opacity fade-in."

- Observation: "The letters are widely spaced and the text appears to move from left to right."
- Hypothesis: "AE: possible method is Text Animator Tracking + Position X animation."
"""


def get_typography_prompt(text: str) -> str:
    """返回当前版本 Typography 分析 Prompt。"""
    return TYPOGRAPHY_ANALYSIS_PROMPT.replace("{text}", text)
