from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import api
from db.library import SourceIdentityMismatch
from projects.service import ContentMismatch, ProjectService
from projects.session import SessionState, read_session, write_session

router = APIRouter()


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


class PathRequest(BaseModel):
    path: str


@router.get("/projects")
def projects():
    from db.paths import resolve_path

    lib = api._get_library()
    rows = []
    for p in lib.list_projects():
        rows.append(
            {
                **asdict(p),
                "name": p.display_name or p.name,
                "internal_name": p.name,
                "shot_count": lib.count_current_shots(p.id),
                "source_available": bool(p.video_path and resolve_path(p.video_path).is_file()),
            }
        )
    return {"projects": rows}


@router.post("/project/save")
@api._exclusive_project_operation
def save():
    try:
        pid = ProjectService(api._get_library()).save_current(api._project_state)
        api._project_state.library_project_id = pid
        write_session(SessionState(project_id=pid))
        api._persist_project_state()
        return {"project_id": pid}
    except SourceIdentityMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/projects/{pid}/name")
@api._exclusive_project_operation
def rename(pid: int, req: NameRequest):
    try:
        result = ProjectService(api._get_library()).rename(pid, req.name)
        if api._project_state.library_project_id == pid:
            api._project_state.display_name = result.display_name
        return asdict(result)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/projects/{pid}/relink")
@api._exclusive_project_operation
def relink(pid: int, req: PathRequest):
    try:
        result = ProjectService(api._get_library()).relink(pid, Path(req.path))
        if api._project_state.library_project_id == pid:
            api._project_state.video_path = result.video_path
        return asdict(result)
    except ContentMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/session")
def session():
    return read_session()


@router.put("/session")
@api._exclusive_project_operation
def set_session(state: SessionState):
    if state.project_id is not None:
        try:
            api._get_library().get_project(state.project_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
    write_session(state)
    return state


class LegacyRequest(BaseModel):
    source_db: str
    source_root: str


@router.post("/projects/import-legacy")
@api._exclusive_project_operation
def import_legacy(req: LegacyRequest):
    from app.runtime_paths import get_runtime_paths
    from projects.legacy_import import import_legacy_library

    try:
        result = import_legacy_library(
            Path(req.source_db), Path(req.source_root), get_runtime_paths()
        )
        api.reset_library()
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(400, f"导入失败，目标库未更改：{exc}") from exc
