"""Shot CRUD and serialization helpers for SQLite."""

from __future__ import annotations

import json
from typing import Any

from db.connection import get_sqlite_connection
from db.models import LibraryShot
from db.paths import resolve_path, store_path


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _row_to_shot(row: Any, tags: list[str] | None = None) -> LibraryShot:
    return LibraryShot(
        id=row["id"],
        project_id=row["project_id"],
        shot_id=row["shot_id"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        duration=row["duration"],
        thumbnail_path=row["thumbnail_path"],
        frame_paths=_json_loads(row["frame_paths"], []),
        observations=_json_loads(row["observations"], {}),
        motion=_json_loads(row["motion"], {}),
        measured_motion=_json_loads(row["measured_motion"], {}),
        motion_summary=_json_loads(row["motion_summary"], {}),
        # The schema0/2 -> 3 migration uses this reader before M6 columns exist.
        rhythm=_json_loads(row["rhythm_json"], {}) if 'rhythm_json' in row.keys() else {},
        typography=_json_loads(row["typography"], {}),
        text_regions=_json_loads(row["text_regions"], []),
        typography_tracks=_json_loads(row["typography_tracks"], []),
        ae_hypothesis=_json_loads(row["ae_hypothesis"], {}),
        ae_recipe=_json_loads(row["ae_recipe"], {}),
        visual_effects=_json_loads(row["visual_effects"], []),
        analysis_error=row["analysis_error"] or "",
        has_text=bool(row["has_text"]),
        motion_type=row["motion_type"] or "",
        motion_confidence=row["motion_confidence"],
        scene_type=row["scene_type"],
        analysis_version=row["analysis_version"],
        pipeline_version=row["pipeline_version"],
        provider_versions=_json_loads(row["provider_versions"], {}),
        tags=tags or [],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _shot_to_row(shot: LibraryShot) -> dict[str, Any]:
    return {
        "project_id": shot.project_id,
        "shot_id": shot.shot_id,
        "start_time": shot.start_time,
        "end_time": shot.end_time,
        "duration": shot.duration,
        "thumbnail_path": shot.thumbnail_path,
        "frame_paths": json.dumps(shot.frame_paths, ensure_ascii=False),
        "observations": json.dumps(shot.observations, ensure_ascii=False),
        "motion": json.dumps(shot.motion, ensure_ascii=False),
        "measured_motion": json.dumps(shot.measured_motion, ensure_ascii=False),
        "motion_summary": json.dumps(shot.motion_summary, ensure_ascii=False),
        "rhythm_json": json.dumps(shot.rhythm, ensure_ascii=False),
        "typography": json.dumps(shot.typography, ensure_ascii=False),
        "text_regions": json.dumps(shot.text_regions, ensure_ascii=False),
        "typography_tracks": json.dumps(shot.typography_tracks, ensure_ascii=False),
        "ae_hypothesis": json.dumps(shot.ae_hypothesis, ensure_ascii=False),
        "ae_recipe": json.dumps(shot.ae_recipe, ensure_ascii=False),
        "visual_effects": json.dumps(shot.visual_effects, ensure_ascii=False),
        "analysis_error": shot.analysis_error,
        "has_text": 1 if shot.has_text else 0,
        "motion_type": shot.motion_type,
        "motion_confidence": shot.motion_confidence,
        "scene_type": shot.scene_type,
        "analysis_version": shot.analysis_version,
        "pipeline_version": shot.pipeline_version,
        "provider_versions": json.dumps(shot.provider_versions, ensure_ascii=False),
    }


def _shot_from_pydantic(shot: Any, project_id: int) -> LibraryShot:
    """Convert a Pydantic Shot to a LibraryShot row model."""
    data = shot.model_dump() if hasattr(shot, "model_dump") else dict(shot)
    return LibraryShot(
        id=0,
        project_id=project_id,
        shot_id=data.get("shot_id", ""),
        start_time=data.get("time", {}).get("start", 0.0),
        end_time=data.get("time", {}).get("end", 0.0),
        duration=data.get("time", {}).get("duration", 0.0),
        thumbnail_path=data.get("frames", [None])[0] if data.get("frames") else None,
        frame_paths=data.get("frames", []),
        observations=data.get("observations", {}),
        motion=data.get("motion", {}),
        measured_motion=data.get("measured_motion", {}),
        motion_summary=data.get("motion_summary", {}),
        rhythm=data.get('rhythm', {}),
        typography=data.get("typography", {}),
        text_regions=[r.model_dump() if hasattr(r, "model_dump") else r for r in data.get("text_regions", [])],
        typography_tracks=[t.model_dump() if hasattr(t, "model_dump") else t for t in data.get("typography_tracks", [])],
        ae_hypothesis=data.get("ae_hypothesis", {}),
        ae_recipe=data.get("ae_recipe", {}),
        visual_effects=data.get("visual_effects", []),
        analysis_error=data.get("analysis_error", ""),
        has_text=bool(data.get("typography_tracks") or data.get("text_regions") or data.get("typography", {}).get("has_text")),
        motion_type=data.get("motion_summary", {}).get("fused_type") or data.get("motion", {}).get("type", ""),
        motion_confidence=data.get("motion_summary", {}).get("fused_confidence", data.get("motion", {}).get("confidence", 0)),
        scene_type=data.get("observations", {}).get("scene_type", ""),
        analysis_version=data.get("analysis_version", "mra-analysis-v1"),
        pipeline_version=data.get("pipeline_version", "mra-pipeline-v1"),
        provider_versions=data.get("provider_versions", {}),
        tags=[],
    )


class ShotRepository:
    """Repository for Shot persistence."""

    def __init__(self) -> None:
        self._conn = get_sqlite_connection()

    def save(self, shot: LibraryShot, commit: bool = True) -> int:
        existing = self._conn.execute(
            "SELECT shot_id FROM shots WHERE project_id=? AND start_time=? AND end_time=? AND analysis_version=?",
            (shot.project_id, shot.start_time, shot.end_time, shot.analysis_version),
        ).fetchone()
        if existing:
            shot.shot_id = existing["shot_id"]
        row = _shot_to_row(shot)
        self._conn.execute(
            """
            INSERT INTO shots (
                project_id, shot_id, start_time, end_time, duration,
                thumbnail_path, frame_paths, observations, motion, measured_motion,
                motion_summary, typography, text_regions, typography_tracks,
                ae_hypothesis, ae_recipe, visual_effects, analysis_error,
                has_text, motion_type, motion_confidence, scene_type,
                analysis_version, pipeline_version, provider_versions, rhythm_json
            ) VALUES (
                :project_id, :shot_id, :start_time, :end_time, :duration,
                :thumbnail_path, :frame_paths, :observations, :motion, :measured_motion,
                :motion_summary, :typography, :text_regions, :typography_tracks,
                :ae_hypothesis, :ae_recipe, :visual_effects, :analysis_error,
                :has_text, :motion_type, :motion_confidence, :scene_type,
                :analysis_version, :pipeline_version, :provider_versions, :rhythm_json
            )
            ON CONFLICT(project_id, start_time, end_time, analysis_version) DO UPDATE SET
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                duration = excluded.duration,
                thumbnail_path = excluded.thumbnail_path,
                frame_paths = excluded.frame_paths,
                observations = excluded.observations,
                motion = excluded.motion,
                measured_motion = excluded.measured_motion,
                motion_summary = excluded.motion_summary,
                typography = excluded.typography,
                text_regions = excluded.text_regions,
                typography_tracks = excluded.typography_tracks,
                ae_hypothesis = excluded.ae_hypothesis,
                ae_recipe = excluded.ae_recipe,
                visual_effects = excluded.visual_effects,
                analysis_error = excluded.analysis_error,
                has_text = excluded.has_text,
                motion_type = excluded.motion_type,
                motion_confidence = excluded.motion_confidence,
                scene_type = excluded.scene_type,
                analysis_version = excluded.analysis_version,
                pipeline_version = excluded.pipeline_version,
                provider_versions = excluded.provider_versions,
                rhythm_json = excluded.rhythm_json,
                updated_at = datetime('now')
            """,
            row,
        )
        if commit:
            self._conn.commit()
        return self._conn.execute(
            "SELECT id FROM shots WHERE project_id=? AND start_time=? AND end_time=? AND analysis_version=?",
            (shot.project_id, shot.start_time, shot.end_time, shot.analysis_version),
        ).fetchone()[0]

    def get_by_id(self, db_id: int) -> LibraryShot | None:
        row = self._conn.execute("SELECT * FROM shots WHERE id=?", (db_id,)).fetchone()
        return _row_to_shot(row) if row is not None else None

    def get(self, shot_id: str, project_id: int) -> LibraryShot | None:
        row = self._conn.execute(
            "SELECT * FROM shots WHERE shot_id = ? AND project_id = ? ORDER BY id DESC LIMIT 1",
            (shot_id, project_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_shot(row)

    def list_by_project(self, project_id: int) -> list[LibraryShot]:
        rows = self._conn.execute(
            "SELECT * FROM shots WHERE project_id = ? ORDER BY start_time ASC",
            (project_id,),
        ).fetchall()
        return [_row_to_shot(row) for row in rows]

    def delete(self, shot_id: str, project_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM shots WHERE id=(SELECT id FROM shots WHERE shot_id=? AND project_id=? ORDER BY id DESC LIMIT 1)",
            (shot_id, project_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def upsert_from_pydantic(self, shot: Any, project_id: int, commit: bool = True) -> int:
        row = _shot_from_pydantic(shot, project_id)
        project = self._conn.execute("SELECT assets_dir FROM projects WHERE id=?", (project_id,)).fetchone()
        assets = project[0] if project else None
        if assets:
            from pathlib import Path
            row.frame_paths = [store_path(resolve_path(assets) / "shots" / row.shot_id / name)
                               if not Path(name).is_absolute() and len(Path(name).parts) == 1
                               else store_path(name) for name in row.frame_paths]
            row.thumbnail_path = row.frame_paths[0] if row.frame_paths else None
        return self.save(row, commit=commit)
