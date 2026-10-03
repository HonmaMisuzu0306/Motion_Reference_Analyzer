"""Bounded verification cache for read-only metadata; submissions still hash afresh."""
from collections import OrderedDict
from pathlib import Path
from threading import RLock

from db.paths import video_hash

_verified = OrderedDict()
_lock = RLock()


def fingerprint(path: Path):
    stat = path.stat()
    return (str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def source_digest(path: Path, *, fresh=False, hasher=None):
    key = fingerprint(path)
    with _lock:
        if not fresh and key in _verified:
            _verified.move_to_end(key)
            return _verified[key]
    digest = (hasher or video_hash)(path)
    if fingerprint(path) != key:
        raise OSError('验证期间源视频发生变化')
    with _lock:
        _verified[key] = digest
        while len(_verified) > 128:
            _verified.popitem(last=False)
    return digest
