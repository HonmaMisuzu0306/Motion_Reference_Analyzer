"""Portable references for assets inside the repository; external files stay absolute."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def store_path(value: str | Path | None) -> str | None:
    if not value:
        return None
    if str(value).startswith('@data/'):
        return str(value)
    path = Path(value)
    from app.runtime_paths import get_runtime_paths
    data = get_runtime_paths().data_root
    if path.is_absolute() and path.resolve().is_relative_to(data) and data != ROOT / 'output':
        return '@data/' + path.resolve().relative_to(data).as_posix()
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    from app.runtime_paths import get_runtime_paths
    if value.startswith('@data/'):
        return get_runtime_paths().data_root / value.removeprefix('@data/')
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def video_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
