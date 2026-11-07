import hashlib
import json
import math
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from schemas.measured_motion import MeasuredMotion

CV_ALGORITHM_VERSION = "v10-robust-consensus"


class MotionCache:
    """CV 运动测量结果缓存。

    缓存 Key 包含视频内容身份、精确镜头时间范围、CV 算法版本、采样配置，
    与 Vision Cache 隔离，避免污染。

    source_hash 只能由调用方在本次分析中验证后传入；调用方还需在发布结果前
    重新验证源视频。省略时每次计算内容哈希，不跨请求信任文件名或时间戳。
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _video_fingerprint(self, video_path: Path) -> str:
        """Content identity survives renames and detects same-size/mtime replacements."""
        digest = hashlib.sha256()
        with Path(video_path).open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def _make_key(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        target_fps: float,
        max_long_edge: int,
        *,
        source_hash: str | None = None,
    ) -> str:
        start, end, fps = float(start_time), float(end_time), float(target_fps)
        if not all(math.isfinite(value) for value in (start, end, fps)):
            raise ValueError('CV 缓存时间和采样率必须是有限数值')
        if not 0 <= start < end or fps <= 0:
            raise ValueError('CV 缓存需要有效镜头范围与正采样率')
        if not isinstance(max_long_edge, int) or isinstance(max_long_edge, bool) or max_long_edge <= 0:
            raise ValueError('CV 缓存最长边必须是正整数')
        if source_hash is None:
            source_hash = self._video_fingerprint(video_path)
        elif not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', source_hash):
            raise ValueError('CV 缓存源内容身份必须为 SHA256')
        # float.hex preserves sub-millisecond boundaries without 8 vs 8.0 key drift.
        raw = json.dumps({
            'source_hash': source_hash.lower(),
            'start': start.hex(), 'end': end.hex(), 'fps': fps.hex(),
            'max_long_edge': max_long_edge, 'algorithm': CV_ALGORITHM_VERSION,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        target_fps: float = 8,
        max_long_edge: int = 720,
        *,
        source_hash: str | None = None,
    ) -> MeasuredMotion | None:
        key = self._make_key(video_path, start_time, end_time, target_fps, max_long_edge,
                             source_hash=source_hash)
        cache_path = self._cache_path(key)
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            # Reject NaN/Infinity, including overflow such as 1e999 and nested pairs.
            json.dumps(data, allow_nan=False)
            if not isinstance(data, dict) or not {'status', 'sample_count', 'pairs'} <= data.keys():
                return None
            result = MeasuredMotion.model_validate(data)
            return None if result.status == 'failed' else result
        except (OSError, ValueError, TypeError, RecursionError):
            # Leave the file alone: another writer may be replacing it concurrently.
            return None

    def set(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        result: MeasuredMotion,
        target_fps: float = 8,
        max_long_edge: int = 720,
        *,
        source_hash: str | None = None,
    ) -> Path:
        key = self._make_key(video_path, start_time, end_time, target_fps, max_long_edge,
                             source_hash=source_hash)
        cache_path = self._cache_path(key)
        # Decode/IO failures are retryable; never replace a usable entry with a failure.
        if result.status == 'failed':
            return cache_path
        data = result.model_dump_safe()
        MeasuredMotion.model_validate(data)
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        temporary = None
        try:
            with NamedTemporaryFile('w', encoding='utf-8', dir=self.cache_dir,
                                    prefix=key + '.', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, cache_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return cache_path
