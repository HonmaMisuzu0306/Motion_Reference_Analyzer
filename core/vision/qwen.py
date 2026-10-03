import base64
import io
import logging
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from ocr.typography_parser import parse_typography_output
from ocr.typography_prompts import get_typography_prompt
from schemas.typography import TypographyAnalysis
from schemas.vision import VisionAnalysis
from vision.parser import parse_vision_output
from vision.prompts import get_shot_analysis_prompt
from vision.provider import ShotContext, VisionProvider

logger = logging.getLogger(__name__)

# 实测依据（Ollama 0.35.0 + qwen3-vl:4b）：
# 1. /v1/chat/completions 不透传 options.num_ctx，真实 3 帧请求(~6800 tokens)
#    超过默认 4096 ctx 会直接 400；原生 /api/chat 支持 options.num_ctx。
# 2. 0.35.0 的 Qwen3VLParser.Init 忽略 thinkValue，只有非空 assistant prefill
#    才从 content 状态开始。显式结束思考并约束 JSON 生成，避免思考耗尽预算。
DEFAULT_NUM_CTX = 16384
DEFAULT_NUM_PREDICT = 8192
OUTPUT_PROTOCOL_VERSION = "json-prefill-v1"


class QwenVisionProvider(VisionProvider):
    """基于 Qwen3-VL 的本地视觉语言模型 Provider。

    通过 Ollama 原生 /api/chat 端点调用（OpenAI-compatible /v1 无法按请求
    设置 num_ctx，真实多帧请求会超过默认 4096 上下文而失败）。
    需要本地先部署 Qwen3-VL 模型，例如：
        ollama pull qwen3-vl:4b
    """

    def __init__(
        self,
        model_id: str = "qwen3-vl:4b",
        api_base: str = "http://127.0.0.1:11434",
        api_key: str = "ollama",
        timeout: float = 120.0,
        num_ctx: int = DEFAULT_NUM_CTX,
        num_predict: int = DEFAULT_NUM_PREDICT,
    ) -> None:
        self.model_id = model_id
        # 防御旧配置：允许传入 .../v1，统一归一化为原生端点根路径
        base = api_base.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        self.api_base = base
        self.api_key = api_key
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self._client = httpx.Client(timeout=timeout)

    def _encode_image(self, image_path: Path) -> str:
        """将图片编码为 base64 裸串（Ollama 原生 images 字段格式）。"""
        return base64.b64encode(image_path.read_bytes()).decode("utf-8")

    def _json_payload(self, messages: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
        # Do not prefill any observations: all JSON values come from the model.
        schema["required"] = [key for key in schema["properties"] if key != "analysis_error"]
        return {
            "model": self.model_id,
            "messages": messages + [{"role": "assistant", "content": "<think>\n\n</think>\n\n"}],
            "stream": False,
            "think": False,
            "format": schema,
            "options": {
                "temperature": 0.2,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }

    def _response_content(self, data: dict[str, Any]) -> str:
        raw = data.get("message", {}).get("content") or ""
        if data.get("done_reason") == "length" or not raw.strip():
            raise RuntimeError(
                "VLM generation incomplete "
                f"(done_reason={data.get('done_reason')}, eval_count={data.get('eval_count')}, "
                f"content_len={len(raw)}, "
                f"thinking_len={len(data.get('message', {}).get('thinking') or '')})"
            )
        return raw

    def _build_messages(self, images: list[Path], context: ShotContext) -> list[dict[str, Any]]:
        prompt = get_shot_analysis_prompt()

        # 追加镜头上下文提示，帮助模型理解这是同一镜头的时间序列帧
        context_text = (
            f"\n\nAdditional context: these {len(images)} frames are from the SAME shot "
            f"({context.shot_id}) from {context.start_time:.2f}s to {context.end_time:.2f}s. "
            "Analyze them as a temporal sequence, not as separate shots."
        )

        return [
            {"role": "system", "content": "你是严谨的视频参考分析助手。所有自然语言说明、运动描述和建议必须使用简体中文；JSON 键、稳定枚举值和源文字保持原样。"},
            {
                "role": "user",
                "content": prompt + context_text,
                "images": [self._encode_image(p) for p in images],
            },
        ]

    def analyze_shot(
        self,
        images: list[Path],
        context: ShotContext,
    ) -> VisionAnalysis:
        """调用本地 Qwen3-VL 模型分析镜头。"""
        if not images:
            return VisionAnalysis(analysis_error="没有提供图片给 QwenVisionProvider")

        messages = self._build_messages(images, context)
        payload = self._json_payload(messages, VisionAnalysis.model_json_schema())

        try:
            response = self._client.post(
                f"{self.api_base}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            raw = self._response_content(data)
            return parse_vision_output(raw)

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.error("无法连接或请求超时到 VLM endpoint %s: %s", self.api_base, exc)
            return VisionAnalysis(
                analysis_error=(
                    f"无法连接到本地 VLM endpoint ({self.api_base})，原因: {exc}。"
                    f"请确认 Ollama 等服务已启动并已拉取模型 {self.model_id}。"
                ),
            )
        except httpx.HTTPStatusError as exc:
            logger.error("VLM endpoint 返回错误: %s", exc)
            return VisionAnalysis(
                analysis_error=f"VLM endpoint 返回 HTTP 错误: {exc.response.status_code} - {exc.response.text[:200]}",
            )
        except Exception as exc:
            logger.error("Qwen vision analysis failed: %s", exc)
            return VisionAnalysis(analysis_error=f"Qwen vision analysis failed: {exc}")

    def analyze_text_region(
        self,
        image_path: Path,
        crop_bbox: tuple[float, float, float, float],
        text: str,
        context: dict[str, Any],
    ) -> TypographyAnalysis:
        """调用本地 Qwen3-VL 模型分析单个文字区域。"""
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                x = int(crop_bbox[0] * w)
                y = int(crop_bbox[1] * h)
                crop_w = int(crop_bbox[2] * w)
                crop_h = int(crop_bbox[3] * h)
                cropped = img.crop((x, y, x + crop_w, y + crop_h))

                buf = io.BytesIO()
                cropped.save(buf, format="JPEG", quality=90)
                encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as exc:
            return TypographyAnalysis(observations=[f"无法裁剪文字区域: {exc}"],
                                      analysis_error=f"无法裁剪文字区域: {exc}")

        prompt = get_typography_prompt(text)
        context_text = (
            f"\n\nContext: this text region is from shot {context.get('shot_id', '')} "
            f"at {context.get('timestamp', 0.0):.2f}s. "
            "Analyze only the typography shown in the crop."
        )

        messages = [
            {"role": "system", "content": "你是严谨的文字排版分析助手。所有自然语言说明和建议必须使用简体中文；JSON 键、稳定枚举值和源文字保持原样。"},
            {
                "role": "user",
                "content": prompt + context_text,
                "images": [encoded],
            },
        ]

        payload = self._json_payload(messages, TypographyAnalysis.model_json_schema())

        try:
            response = self._client.post(
                f"{self.api_base}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            raw = self._response_content(data)
            return parse_typography_output(raw)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            return TypographyAnalysis(
                observations=[f"无法连接到本地 VLM endpoint: {exc}"],
                analysis_error=f"无法连接到本地 VLM endpoint: {exc}",
            )
        except Exception as exc:
            return TypographyAnalysis(observations=[f"Typography 分析失败: {exc}"],
                                      analysis_error=f"Typography 分析失败: {exc}")

    def analyze_static_frame(self, image: Path, context: dict):
        from selection.static import StaticVisionAnalysis
        from vision.prompts import get_static_frame_prompt

        try:
            messages = [{'role': 'system', 'content': '你是严谨的静态画面分析助手。描述使用简体中文。'},
                        {'role': 'user', 'content': get_static_frame_prompt(),
                         'images': [self._encode_image(image)]}]
            response = self._client.post(f'{self.api_base}/api/chat',
                                         json=self._json_payload(messages, StaticVisionAnalysis.model_json_schema()))
            response.raise_for_status()
            return StaticVisionAnalysis.model_validate_json(self._response_content(response.json()))
        except Exception as exc:
            return StaticVisionAnalysis(analysis_error=f'单帧视觉分析失败：{exc}')

    def get_model_info(self) -> dict[str, Any]:
        return {
            "provider": "qwen3-vl",
            "model_id": self.model_id,
            "api_base": self.api_base,
            "endpoint": f"{self.api_base}/api/chat",
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "output_protocol_version": OUTPUT_PROTOCOL_VERSION,
            "supports_multi_image": self.supports_multi_image,
        }
