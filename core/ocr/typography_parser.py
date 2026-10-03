import json
import re
from typing import Any

from pydantic import ValidationError

from schemas.typography import TypographyAnalysis


def _extract_json_block(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _clean_json_text(text: str) -> str:
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    text = re.sub(r"//[^\n]*", "", text)
    text = text.replace("'", '"')
    return text


def _safe_load_json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def parse_typography_output(raw: str) -> TypographyAnalysis:
    """将模型原始输出解析为 TypographyAnalysis。"""
    if not raw or not raw.strip():
        return TypographyAnalysis(
            observations=["模型返回空输出"],
            analysis_error="模型返回空输出",
        )

    extracted = _extract_json_block(raw)
    data = _safe_load_json(extracted)
    if data is None:
        cleaned = _clean_json_text(extracted)
        data = _safe_load_json(cleaned)

    if data is None:
        return TypographyAnalysis(
            observations=[f"无法从模型输出解析 JSON: {raw[:200]}"],
            analysis_error=f"无法从模型输出解析 JSON: {raw[:200]}",
        )

    try:
        return TypographyAnalysis.model_validate(data)
    except ValidationError as exc:
        # 宽松处理：将非法枚举值替换为 unknown
        for key in list(data.keys()):
            if isinstance(data[key], str) and data[key].strip() == "":
                data[key] = "unknown"
        try:
            return TypographyAnalysis.model_validate(data)
        except ValidationError:
            return TypographyAnalysis(
                observations=[f"Typography 解析失败: {exc.errors()[:3]}"],
                analysis_error=f"Typography 解析失败: {exc.errors()[:3]}",
            )
