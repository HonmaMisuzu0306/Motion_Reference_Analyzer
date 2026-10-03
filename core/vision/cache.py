import hashlib
import json
from pathlib import Path
from typing import Any

from schemas.vision import VisionAnalysis


class VisionCache:
    """基于文件系统的简单 Vision 分析结果缓存。

    缓存 Key 由镜头身份、有序帧内容哈希、模型配置和 Prompt 版本组成。
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._frame_hashes: dict[tuple[str, int, int, int], bytes] = {}

    def _compute_frame_hash(self, image_paths: list[Path]) -> str:
        """保留时间顺序，按帧内容计算哈希；元数据仅用于本次运行内复用哈希。"""
        hasher = hashlib.sha256()
        for path in image_paths:
            stat = path.stat()
            identity = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            if identity not in self._frame_hashes:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                self._frame_hashes[identity] = digest.digest()
            hasher.update(self._frame_hashes[identity])
        return hasher.hexdigest()

    def _make_key(
        self,
        shot_id: str,
        image_paths: list[Path],
        model_id: str,
        prompt_version: str,
        model_info: dict[str, Any] | None = None,
    ) -> str:
        frame_hash = self._compute_frame_hash(image_paths)
        raw = json.dumps({
            "shot_id": shot_id,
            "frame_hash": frame_hash,
            "model_id": model_id,
            "model_info": model_info or {},
            "prompt_version": prompt_version,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        shot_id: str,
        image_paths: list[Path],
        model_id: str,
        prompt_version: str,
        model_info: dict[str, Any] | None = None,
    ) -> VisionAnalysis | None:
        """尝试从缓存读取分析结果。"""
        key = self._make_key(shot_id, image_paths, model_id, prompt_version, model_info)
        cache_path = self._cache_path(key)
        if not cache_path.exists():
            return None

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return VisionAnalysis.model_validate(data)
        except Exception:
            return None

    def set(
        self,
        shot_id: str,
        image_paths: list[Path],
        model_id: str,
        prompt_version: str,
        result: VisionAnalysis,
        model_info: dict[str, Any] | None = None,
    ) -> Path:
        """将分析结果写入缓存。"""
        key = self._make_key(shot_id, image_paths, model_id, prompt_version, model_info)
        cache_path = self._cache_path(key)
        cache_path.write_text(
            json.dumps(result.model_dump_safe(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return cache_path
