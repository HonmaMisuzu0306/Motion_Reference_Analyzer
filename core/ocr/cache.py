"""OCR 结果缓存。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from schemas.typography import TextRegion


class OCRCache:
    """基于文件系统的 OCR 结果缓存。

    缓存 Key 由视频身份、Shot 时间范围、采样配置、OCR Provider/模型/算法版本组成。
    """

    def __init__(self, cache_dir: Path, algorithm_version: str = "v3-video-clock") -> None:
        self.cache_dir = cache_dir
        self.algorithm_version = algorithm_version
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._video_hashes: dict[tuple[str, int, int, int], str] = {}

    def _video_hash(self, video_path: Path) -> str:
        """基于内容识别视频；同一分析内复用未改变文件的内容哈希。"""
        if not video_path.exists():
            return hashlib.sha256(str(video_path).encode("utf-8")).hexdigest()[:16]
        stat = video_path.stat()
        identity = (str(video_path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if identity not in self._video_hashes:
            digest = hashlib.sha256()
            with video_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            self._video_hashes[identity] = digest.hexdigest()
        return self._video_hashes[identity]

    def _make_key(
        self,
        video_path: Path,
        start: float,
        end: float,
        model_info: dict[str, Any],
        sample_config: dict[str, Any],
    ) -> str:
        video_hash = self._video_hash(video_path)
        config = {
            "video_hash": video_hash,
            "start": start,
            "end": end,
            "model_info": model_info,
            "sample_config": sample_config,
            "algorithm_version": self.algorithm_version,
        }
        raw = json.dumps(config, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        video_path: Path,
        start: float,
        end: float,
        model_info: dict[str, Any],
        sample_config: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """读取缓存的 OCR 帧结果。"""
        key = self._make_key(video_path, start, end, model_info, sample_config)
        cache_path = self._cache_path(key)
        if not cache_path.exists():
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def set(
        self,
        video_path: Path,
        start: float,
        end: float,
        model_info: dict[str, Any],
        sample_config: dict[str, Any],
        frame_results: list[dict[str, Any]],
    ) -> Path:
        """写入 OCR 帧结果缓存。"""
        key = self._make_key(video_path, start, end, model_info, sample_config)
        cache_path = self._cache_path(key)

        def _serialize(obj: Any) -> Any:
            if isinstance(obj, TextRegion):
                return obj.model_dump()
            if isinstance(obj, dict):
                return {k: _serialize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_serialize(i) for i in obj]
            return obj

        cache_path.write_text(
            json.dumps(
                _serialize(frame_results),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return cache_path
