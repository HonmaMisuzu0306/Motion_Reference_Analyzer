"""Content-addressed whole-media cache; cut matching stays outside this cache."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from schemas.audio import AudioAnalysis


class AudioCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def key(self, path: Path, **parameters) -> str:
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        digest.update(json.dumps(parameters, sort_keys=True).encode())
        return digest.hexdigest()

    def get(self, key: str) -> AudioAnalysis | None:
        try:
            result = AudioAnalysis.model_validate_json((self.cache_dir / f'{key}.json').read_text(encoding='utf-8'))
            if result.status in {'pending', 'error'}:
                return None
            return result.model_copy(update={'cache_hit': True})
        except (OSError, ValueError, ValidationError):
            return None

    def set(self, key: str, result: AudioAnalysis):
        if result.status in {'pending', 'error'}:
            return
        target = self.cache_dir / f'{key}.json'
        staging = self.cache_dir / f'{key}.{uuid4().hex}.tmp'
        try:
            staging.write_text(result.model_dump_json(), encoding='utf-8')
            staging.replace(target)
        finally:
            staging.unlink(missing_ok=True)
