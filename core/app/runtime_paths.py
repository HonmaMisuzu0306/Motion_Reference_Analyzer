"""All writable state lives outside the installed application."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    data_root: Path
    legacy_root: Path

    @property
    def database(self):
        return self.data_root / "mra_library.db"

    @property
    def projects(self):
        return self.data_root

    @property
    def cache(self):
        return self.data_root / "cache"

    @property
    def logs(self):
        return self.data_root / "logs"

    @property
    def settings(self):
        return self.data_root / "settings.json"

    @property
    def session(self):
        return self.data_root / "session.json"

    @property
    def exports(self):
        return self.data_root / "exports"


def get_runtime_paths() -> RuntimePaths:
    legacy = Path(os.environ.get("MRA_LEGACY_ROOT", Path(__file__).resolve().parents[2]))
    if os.environ.get("MRA_DATA_DIR"):
        data = Path(os.environ["MRA_DATA_DIR"]).resolve()
    elif getattr(sys, "frozen", False):
        data = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "MotionReferenceAnalyzer"
        )
    else:
        data = legacy / "output"
    data.mkdir(parents=True, exist_ok=True)
    return RuntimePaths(data, legacy)
