"""Pydantic schemas for Reference Library API."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1)
    color: str = Field(default="#3b82f6")


class TagResponse(BaseModel):
    id: int
    name: str
    color: str


class ShotTagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)


class FilterRequest(BaseModel):
    query: str = ""
    motion_types: list[str] = Field(default_factory=list)
    has_text: bool | None = None
    min_duration: float | None = Field(default=None, ge=0)
    max_duration: float | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    max_confidence: float | None = Field(default=None, ge=0, le=1)
    project_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_ranges(self):
        for lower, upper in [(self.min_duration, self.max_duration),
                             (self.min_confidence, self.max_confidence)]:
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("Filter minimum must not exceed maximum")
        return self


class LibraryProjectSummary(BaseModel):
    id: int
    name: str
    video_filename: str
    video_duration: float
    analysis_status: str
    updated_at: str


class LibraryShotSummary(BaseModel):
    id: int
    project_id: int
    shot_id: str
    start_time: float
    end_time: float
    duration: float
    thumbnail_path: str | None
    motion_type: str
    has_text: bool
    tags: list[str] = Field(default_factory=list)
    motion_confidence: float = 0
    scene_type: str = ""


class LibrarySearchResponse(BaseModel):
    shots: list[LibraryShotSummary]
    motion_types: list[str] = Field(default_factory=list)
