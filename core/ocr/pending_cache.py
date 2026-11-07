"""Hold whole-project OCR writes until the caller revalidates source content."""
from copy import deepcopy
from pathlib import Path

from ocr.cache import OCRCache


class PendingOCRCache(OCRCache):
    def __init__(self, cache_dir: Path, source_path: Path, source_hash: str):
        super().__init__(cache_dir, algorithm_version='v6-verified-square-pixel-display')
        if len(source_hash) != 64 or any(c not in '0123456789abcdef' for c in source_hash):
            raise ValueError('OCR 缓存需要已验证的 SHA256')
        self.source_path = source_path.resolve()
        self.source_hash = source_hash
        self.pending = []

    def _video_hash(self, video_path: Path) -> str:
        if video_path.resolve() != self.source_path:
            raise ValueError('OCR 缓存不能跨源视频使用')
        return self.source_hash

    def set(self, video_path, start, end, model_info, sample_config, frame_results):
        key = self._make_key(video_path, start, end, model_info, sample_config)
        self.pending.append(deepcopy((video_path, start, end, model_info, sample_config, frame_results)))
        return self._cache_path(key)

    def publish(self):
        """Call only after source content still matches source_hash."""
        for args in self.pending:
            super().set(*args)
        self.pending.clear()
