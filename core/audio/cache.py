"""Content-addressed whole-media cache; cut matching stays outside this cache."""
import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from schemas.audio import AudioAnalysis

AUDIO_CACHE_VERSION = 'audio-source-verified-v1'


def source_digest(path: Path) -> str:
    """Read content afresh; size and timestamps cannot detect in-place replacements."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class AudioCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def key(self, path: Path, *, source_hash: str | None = None, **parameters) -> str:
        """source_hash must be verified for this request and rechecked before publish."""
        if source_hash is None:
            source_hash = source_digest(path)
        elif not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', source_hash):
            raise ValueError('音频缓存源内容身份必须为 SHA256')
        # Old keys could contain results computed after the source had changed.
        # A new namespace prevents those unverified entries from being reused.
        identity = {'version': AUDIO_CACHE_VERSION, 'source_hash': source_hash.lower(),
                    'parameters': parameters}
        return hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()

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
