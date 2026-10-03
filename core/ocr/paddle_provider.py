"""PaddleOCR 本地 OCR Provider 实现。

支持多语言识别（日语/中文/英语），返回结构化 TextRegion。
应用通过已验证的外部本地模型目录初始化，不下载权重。
"""

from __future__ import annotations

import importlib.metadata
import logging
import re
from typing import Any

import numpy as np

from ocr.provider import OCRProvider
from schemas.typography import BBox, NormalizedBBox, TextRegion

logger = logging.getLogger(__name__)

_HIRAGANA = re.compile(r"[\u3040-\u309F]")
_KATAKANA = re.compile(r"[\u30A0-\u30FF]")
_CJK = re.compile(r"[\u4E00-\u9FFF]")
_LATIN = re.compile(r"[A-Za-z]")


def _detect_language(text: str) -> str:
    """轻量语言判断：ja / zh / en / mixed / unknown。"""
    has_hira = bool(_HIRAGANA.search(text))
    has_kata = bool(_KATAKANA.search(text))
    has_cjk = bool(_CJK.search(text))
    has_latin = bool(_LATIN.search(text))

    is_ja = has_hira or has_kata
    is_zh = has_cjk and not is_ja

    if is_ja and has_latin:
        return "mixed"
    if is_ja:
        return "ja"
    if is_zh and has_latin:
        return "mixed"
    if is_zh:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


def _normalize_text(text: str) -> str:
    """用于 Track 匹配归一化的文本。"""
    return re.sub(r"\s+", "", text).strip().lower()


def _bbox_from_points(points: list[list[float]]) -> tuple[int, int, int, int]:
    """从 PaddleOCR 四边形点计算轴对齐 bbox。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x = int(min(xs))
    y = int(min(ys))
    w = int(max(xs) - x)
    h = int(max(ys) - y)
    return x, y, max(w, 1), max(h, 1)


def _normalize(
    x: int,
    y: int,
    w: int,
    h: int,
    frame_w: int,
    frame_h: int,
) -> NormalizedBBox:
    """像素 bbox 转归一化 bbox。"""
    return NormalizedBBox(
        x=round(x / frame_w, 4),
        y=round(y / frame_h, 4),
        width=round(w / frame_w, 4),
        height=round(h / frame_h, 4),
    )


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR 本地 OCR Provider。

    当 PaddleOCR / paddlepaddle 未安装或初始化失败时降级为无输出，
    避免整个 Pipeline 崩溃。
    """

    def __init__(
        self,
        languages: list[str] | None = None,
        use_angle_cls: bool = True,
        ocr_version: str = "PP-OCRv5",
        model_paths=None,
    ) -> None:
        self.languages = languages or ["japan"]
        self.use_angle_cls = use_angle_cls
        self.ocr_version = ocr_version
        self.model_paths = model_paths
        self._engines: dict[str, Any] = {}
        self._available = False
        self._error_message = ""
        self._version = "unknown"
        self._model_identity = ""
        self._try_init()

    def _try_init(self) -> None:
        if self.model_paths is not None:
            from models.ocr_paths import validate_ocr_models

            result = validate_ocr_models(self.model_paths)
            if not result.available:
                self._error_message = "；".join(result.errors)
                return
            from models.ocr_paths import model_identity

            self._model_identity = model_identity(self.model_paths)
        try:
            from paddleocr import PaddleOCR, __version__

            self._version = __version__
        except Exception as exc:
            self._error_message = f"PaddleOCR 未安装: {exc}"
            logger.warning(self._error_message)
            return

        try:
            for lang in self.languages:
                options = dict(lang=lang, ocr_version=self.ocr_version)
                if self.model_paths is not None:
                    from models.ocr_paths import local_model_name

                    paths = next((p for p in self.model_paths if p.language == lang), None)
                    if paths is None:
                        raise ValueError(f"{lang} 未配置本地模型")
                    options.update(
                        text_detection_model_dir=str(paths.detection_dir),
                        text_recognition_model_dir=str(paths.recognition_dir),
                        text_detection_model_name=local_model_name(paths.detection_dir),
                        text_recognition_model_name=local_model_name(paths.recognition_dir),
                    )
                    if paths.orientation_dir:
                        options["textline_orientation_model_dir"] = str(paths.orientation_dir)
                        options["textline_orientation_model_name"] = local_model_name(
                            paths.orientation_dir
                        )
                if self._version.startswith("3."):
                    options.update(
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=bool(paths.orientation_dir)
                        if self.model_paths is not None
                        else self.use_angle_cls,
                        enable_mkldnn=False,
                        cpu_threads=4,
                    )
                else:
                    options.update(use_angle_cls=self.use_angle_cls, show_log=False)
                self._engines[lang] = PaddleOCR(**options)
            self._available = True
        except Exception as exc:
            self._error_message = f"PaddleOCR 初始化失败: {exc}"
            logger.warning(self._error_message, exc_info=True)

    @property
    def available(self) -> bool:
        return self._available

    def get_model_info(self) -> dict[str, Any]:
        return {
            "provider": "paddleocr",
            "version": self._version,
            "paddle_version": importlib.metadata.version("paddlepaddle")
            if self._available
            else "unknown",
            "languages": self.languages,
            "use_angle_cls": self.use_angle_cls,
            "ocr_version": self.ocr_version,
            "available": self._available,
            "model_identity": self._model_identity,
            "model_paths": [p.model_dump(mode="json") for p in self.model_paths]
            if self.model_paths is not None
            else [],
            "error_message": self._error_message,
        }

    def analyze_frame(
        self,
        image: np.ndarray,
        frame_timestamp: float = 0.0,
        frame_width: int = 0,
        frame_height: int = 0,
    ) -> list[TextRegion]:
        if not self._available:
            return []

        if image is None or image.size == 0:
            return []

        h, w = image.shape[:2]
        frame_w = frame_width if frame_width > 0 else w
        frame_h = frame_height if frame_height > 0 else h

        regions: list[TextRegion] = []
        seen_texts: set[str] = set()

        # 多语言：依次运行，按归一化文本去重
        for lang, engine in self._engines.items():
            try:
                if self._version.startswith("3."):
                    predictions = list(engine.predict(image))
                    lines = []
                    for prediction in predictions:
                        lines.extend(
                            zip(
                                prediction["rec_polys"],
                                zip(prediction["rec_texts"], prediction["rec_scores"], strict=True),
                                strict=True,
                            )
                        )
                else:
                    results = engine.ocr(image, cls=self.use_angle_cls)
                    lines = results[0] if results and results[0] else []
            except Exception as exc:
                logger.warning("PaddleOCR %s failed: %s", lang, exc)
                raise RuntimeError(f"PaddleOCR {lang} inference failed: {exc}") from exc

            for idx, line in enumerate(lines):
                if line is None or len(line) < 2:
                    continue
                bbox_points, text_info = line[0], line[1]
                if not isinstance(text_info, (list, tuple)) or len(text_info) < 2:
                    continue
                text, conf = text_info[0], float(text_info[1])
                if not text:
                    continue

                x, y, bw, bh = _bbox_from_points(bbox_points)
                norm = _normalize(x, y, bw, bh, frame_w, frame_h)
                norm_text = _normalize_text(text)
                dedup_key = f"{norm_text}:{round(norm.x, 2)}:{round(norm.y, 2)}"
                if dedup_key in seen_texts:
                    continue
                seen_texts.add(dedup_key)

                detected_lang = _detect_language(text)
                orientation = "vertical" if bh > bw * 1.3 else "horizontal"

                regions.append(
                    TextRegion(
                        id=f"{lang}_{idx:03d}",
                        text=text,
                        normalized_text=norm_text,
                        language=detected_lang,
                        confidence=round(conf, 4),
                        bbox_px=BBox(x=x, y=y, width=bw, height=bh),
                        bbox_normalized=norm,
                        center_x=round((x + bw / 2) / frame_w, 4),
                        center_y=round((y + bh / 2) / frame_h, 4),
                        width_ratio=round(bw / frame_w, 4),
                        height_ratio=round(bh / frame_h, 4),
                        orientation=orientation,
                        frame_timestamp=round(frame_timestamp, 3),
                    )
                )

        # 单帧内按置信度排序
        regions.sort(key=lambda r: r.confidence, reverse=True)
        return regions
