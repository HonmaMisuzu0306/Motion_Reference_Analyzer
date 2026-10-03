from ocr.typography_prompts import get_typography_prompt
from vision.prompts import get_shot_analysis_prompt


def test_new_natural_language_output_is_chinese_with_stable_keys():
    for prompt in [get_shot_analysis_prompt(), get_typography_prompt("SUMMER")]:
        assert "Simplified Chinese" in prompt
        assert "JSON keys" in prompt
