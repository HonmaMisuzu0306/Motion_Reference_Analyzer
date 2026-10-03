import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from app.runtime_paths import RuntimePaths, get_runtime_paths
from schemas.settings import UserSettings

_lock = RLock()


def atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as f:
            temp = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


class SettingsStore:
    def __init__(self, paths: RuntimePaths | None = None):
        self.paths = paths or get_runtime_paths()

    def load(self) -> UserSettings:
        with _lock:
            if not self.paths.settings.exists():
                return UserSettings()
            try:
                return UserSettings.model_validate_json(
                    self.paths.settings.read_text(encoding="utf-8")
                )
            except Exception as exc:
                raise ValueError("设置文件损坏，请备份后修复或恢复默认设置") from exc

    def save(self, settings: UserSettings) -> UserSettings:
        with _lock:
            atomic_json(self.paths.settings, settings.model_dump(mode="json"))
        return settings
