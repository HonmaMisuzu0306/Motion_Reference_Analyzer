from pydantic import BaseModel

from app.runtime_paths import get_runtime_paths
from app.settings import atomic_json


class SessionState(BaseModel):
    project_id: int | None = None
    shot_library_id: int | None = None
    shot_id: str | None = None


def read_session() -> SessionState:
    path = get_runtime_paths().session
    try:
        return SessionState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SessionState()


def write_session(state: SessionState):
    atomic_json(get_runtime_paths().session, state.model_dump())
