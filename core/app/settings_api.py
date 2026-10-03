from fastapi import APIRouter, HTTPException

from app import api
from app.config import reset_config
from app.settings import SettingsStore
from schemas.settings import UserSettings

router = APIRouter()


@router.get("/settings")
def settings():
    try:
        return SettingsStore().load()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/settings")
@api._exclusive_project_operation
def save_settings(value: UserSettings):
    SettingsStore().save(value)
    reset_config()
    return value
