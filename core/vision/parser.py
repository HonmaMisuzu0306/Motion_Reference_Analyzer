import json
import re
from typing import Any

from pydantic import ValidationError

from schemas.vision import VisionAnalysis


def _extract_json_block(text: str) -> str:
    """从可能包含 Markdown code fence 的文本中提取 JSON 字符串。"""
    # 优先匹配 ```json ... ``` 或 ``` ... ``` 包裹的 JSON
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    # 否则尝试直接找到第一个顶层 JSON 对象
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    return text.strip()


def _clean_json_text(text: str) -> str:
    """对模型输出的 JSON 做常见容错清理。"""
    # 去除尾部逗号
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    # 去除单行注释
    text = re.sub(r"//[^\n]*", "", text)
    # 将单引号替换为双引号（仅简单场景）
    text = text.replace("'", '"')
    return text


def _safe_load_json(text: str) -> dict[str, Any] | None:
    """尝试解析 JSON，返回字典或 None。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_vision_output(raw: str) -> VisionAnalysis:
    """将模型原始输出解析为 VisionAnalysis。

    解析失败时返回一个带有 analysis_error 的 VisionAnalysis，
    而不是抛出异常，确保单个 Shot 失败不会中断整个 Pipeline。
    """
    if not raw or not raw.strip():
        return VisionAnalysis(
            analysis_error="模型返回空输出",
        )

    # 第一步：提取 JSON 块
    extracted = _extract_json_block(raw)

    # 第二步：尝试直接解析
    data = _safe_load_json(extracted)

    # 第三步：尝试清理后解析
    if data is None:
        cleaned = _clean_json_text(extracted)
        data = _safe_load_json(cleaned)

    if data is None:
        return VisionAnalysis(
            analysis_error=f"无法从模型输出解析 JSON: {raw[:200]}",
        )

    # 第四步：Pydantic 验证
    try:
        return VisionAnalysis.model_validate(data)
    except ValidationError as exc:
        # 尝试宽松解析：将非法枚举值替换为 unknown 后再验证
        relaxed = _relax_enum_values(data)
        try:
            return VisionAnalysis.model_validate(relaxed)
        except ValidationError:
            return VisionAnalysis(
                analysis_error=f"Pydantic 验证失败: {exc.errors()[:3]}",
            )


def _relax_enum_values(data: dict[str, Any]) -> dict[str, Any]:
    """将已知枚举字段中的非法值替换为 unknown，提高容错能力。"""
    enum_fields = {
        "subject_type",
        "subject_position",
        "background_type",
        "type",
        "position",
        "style",
    }

    def walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            result: dict[str, Any] = {}
            for key, value in obj.items():
                if key in enum_fields and isinstance(value, str):
                    result[key] = value if value in _known_enum_values(key) else "unknown"
                else:
                    result[key] = walk(value)
            return result
        if isinstance(obj, list):
            return [walk(item) for item in obj]
        return obj

    return walk(data)


def _known_enum_values(field: str) -> set[str]:
    from schemas.vision import (
        BackgroundType,
        EffectType,
        MotionType,
        SubjectPosition,
        SubjectType,
        TextPosition,
        TextStyle,
    )

    mapping: dict[str, tuple[str, ...]] = {
        "subject_type": SubjectType.__args__,
        "subject_position": SubjectPosition.__args__,
        "background_type": BackgroundType.__args__,
        "type": (*MotionType.__args__, *EffectType.__args__),
        "position": TextPosition.__args__,
        "style": TextStyle.__args__,
    }
    return set(mapping.get(field, ()))
