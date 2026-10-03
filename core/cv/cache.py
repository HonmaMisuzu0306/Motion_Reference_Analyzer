import hashlib
import json
from pathlib import Path

from schemas.measured_motion import MeasuredMotion

CV_ALGORITHM_VERSION = "v2-video-clock"


class MotionCache:
    """CV 运动测量结果缓存。

    缓存 Key 包含视频身份、镜头时间范围、CV 算法版本、采样配置，
    与 Vision Cache 隔离，避免污染。
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _video_fingerprint(self, video_path: Path) -> str:
        """基于文件名、大小、修改时间生成稳定指纹。"""
        stat = video_path.stat()
        raw = f"{video_path.name}:{stat.st_size}:{int(stat.st_mtime)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _make_key(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        target_fps: float,
        max_long_edge: int,
    ) -> str:
        fp = self._video_fingerprint(video_path)
        raw = (
            f"{fp}:"
            f"{start_time:.3f}-{end_time:.3f}:"
            f"{CV_ALGORITHM_VERSION}:"
            f"fps={target_fps}:"
            f"edge={max_long_edge}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        target_fps: float = 8,
        max_long_edge: int = 720,
    ) -> MeasuredMotion | None:
        key = self._make_key(video_path, start_time, end_time, target_fps, max_long_edge)
        cache_path = self._cache_path(key)
        if not cache_path.exists():
            return None

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return MeasuredMotion.model_validate(data)
        except Exception:
            return None

    def set(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        result: MeasuredMotion,
        target_fps: float = 8,
        max_long_edge: int = 720,
    ) -> Path:
        key = self._make_key(video_path, start_time, end_time, target_fps, max_long_edge)
        cache_path = self._cache_path(key)
        cache_path.write_text(
            json.dumps(result.model_dump_safe(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return cache_path
