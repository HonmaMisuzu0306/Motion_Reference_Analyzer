"""Lightweight data models for SQLite persistence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LibraryProject:
    """Project row from SQLite."""

    id: int
    name: str
    video_path: str | None
    video_filename: str
    video_duration: float
    video_width: int
    video_height: int
    video_fps: float
    video_codec: str
    analysis_status: str
    analysis_message: str
    created_at: str
    updated_at: str
    video_hash: str | None = None
    assets_dir: str | None = None
    audio: dict[str, Any] = field(default_factory=dict)
    rhythm_summary: dict[str, Any] = field(default_factory=dict)
    video_has_audio: bool = False
    display_name: str = ""
    last_opened_at: str = ""


@dataclass
class LibraryShot:
    """Shot row from SQLite with tags."""

    id: int
    project_id: int
    shot_id: str
    start_time: float
    end_time: float
    duration: float
    thumbnail_path: str | None
    frame_paths: list[str]
    observations: dict[str, Any]
    motion: dict[str, Any]
    measured_motion: dict[str, Any]
    motion_summary: dict[str, Any]
    typography: dict[str, Any]
    text_regions: list[dict[str, Any]]
    typography_tracks: list[dict[str, Any]]
    ae_hypothesis: dict[str, Any]
    ae_recipe: dict[str, Any]
    visual_effects: list[dict[str, Any]]
    analysis_error: str
    has_text: bool
    motion_type: str
    rhythm: dict[str, Any] = field(default_factory=dict)
    motion_confidence: float = 0.0
    scene_type: str = ""
    analysis_version: str = "mra-analysis-v1"
    pipeline_version: str = "mra-pipeline-v1"
    provider_versions: dict[str, Any] = field(default_factory=dict)
    manual_tags: list[str] = field(default_factory=list)
    automatic_tags: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Tag:
    """Tag row from SQLite."""

    id: int
    name: str
    color: str
    created_at: str = ""


@dataclass
class FilterSet:
    """Search filter parameters."""

    query: str = ""
    motion_types: list[str] = field(default_factory=list)
    has_text: bool | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    tags: list[str] = field(default_factory=list)
    limit: int = 100
    offset: int = 0
    min_confidence: float | None = None
    max_confidence: float | None = None
    project_id: int | None = None
