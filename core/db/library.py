"""Reference Library main facade: project and shot persistence."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import copy
from typing import Any

from db.automatic_tags import automatic_tags
from db.connection import get_sqlite_connection
from db.models import FilterSet, LibraryProject, LibraryShot
from db.paths import ROOT, resolve_path, store_path, video_hash
from db.schema import init_schema
from db.search import SearchRepository
from db.shots import ShotRepository
from db.tags import TagRepository

logger = logging.getLogger(__name__)


class SourceIdentityMismatch(ValueError):
    """The result's captured source does not match the target project or file."""


class ReferenceLibrary:
    """Main entry point for the SQLite Reference Library."""

    def __init__(self) -> None:
        self._fts5_enabled = init_schema(self._conn)

    # The API facade is shared by worker threads; repositories and transactions
    # must always use the calling thread's connection, including lib._tags calls.
    @property
    def _conn(self):
        return get_sqlite_connection()

    @property
    def _projects(self):
        return ProjectRepository(self._conn)

    @property
    def _shots(self):
        return ShotRepository()

    @property
    def _tags(self):
        return TagRepository()

    @property
    def _search(self):
        return SearchRepository()

    @property
    def fts5_enabled(self) -> bool:
        return self._fts5_enabled

    # Project operations
    def save_project(self, project: Any, commit: bool = True) -> int:
        """Persist or update a project from Pydantic Project."""
        return self._projects.upsert_from_pydantic(project, commit=commit)

    def save_analysis(self, project: Any) -> int:
        """One transaction: a failed save never leaves a partially imported analysis."""
        with self._conn:
            pid = self.save_project(project, commit=False)
            self._conn.execute("UPDATE shots SET provider_versions="
                               "json_set(provider_versions,'$.analysis_current',json('false')) "
                               "WHERE project_id=?", (pid,))
            for shot in project.shots:
                saved_shot = copy(shot)
                saved_shot.provider_versions = {**shot.provider_versions, 'analysis_current': True}
                self.save_shot(saved_shot, pid, commit=False)
        return pid

    def load_project(self, project_id: int) -> tuple[LibraryProject, list[LibraryShot]]:
        project = self.get_project(project_id)
        shots = self._current_shots(project_id)
        for shot in shots:
            shot.tags = [t.name for t in self._tags.get_shot_tags(shot.id)]
            shot.manual_tags = self._tags.manual_names(shot.id)
            shot.automatic_tags = self._tags.automatic_names(shot.id)
        return project, shots

    def _current_shots(self, project_id: int) -> list[LibraryShot]:
        shots = self._shots.list_by_project(project_id)
        # Membership is transactional; asset paths may change during import or metadata saves.
        # Unmarked legacy rows remain readable until an analysis defines the current set.
        if any('analysis_current' in shot.provider_versions for shot in shots):
            return [shot for shot in shots if shot.provider_versions.get('analysis_current') is True]
        return shots

    def count_current_shots(self, project_id: int) -> int:
        return len(self._current_shots(project_id))

    def get_project(self, project_id: int) -> LibraryProject:
        project = self._projects.get(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        return project

    def list_projects(self) -> list[LibraryProject]:
        return self._projects.list_all()

    def delete_project(self, project_id: int) -> bool:
        return self._projects.delete(project_id)

    # Shot operations
    def save_shot(self, shot: Any, project_id: int, commit: bool = True) -> int:
        """Persist a single shot. Accepts Pydantic Shot or LibraryShot."""
        if isinstance(shot, LibraryShot):
            db_id = self._shots.save(shot, commit=False)
        else:
            db_id = self._shots.upsert_from_pydantic(shot, project_id, commit=False)
        stored = self._conn.execute("SELECT * FROM shots WHERE id=?", (db_id,)).fetchone()
        from db.shots import _row_to_shot

        self._tags.refresh_automatic(db_id, automatic_tags(_row_to_shot(stored)))
        if commit:
            self._conn.commit()
        return db_id

    def save_shots(self, shots: list[Any], project_id: int) -> list[int]:
        """Persist multiple shots."""
        ids = []
        for shot in shots:
            ids.append(self.save_shot(shot, project_id))
        return ids

    def list_shots(self, project_id: int) -> list[LibraryShot]:
        shots = self._shots.list_by_project(project_id)
        for shot in shots:
            shot.tags = [t.name for t in self._tags.get_shot_tags(shot.id)]
            shot.manual_tags = self._tags.manual_names(shot.id)
            shot.automatic_tags = self._tags.automatic_names(shot.id)
        return shots

    def get_shot(self, db_id: int) -> LibraryShot:
        from db.shots import _row_to_shot

        row = self._conn.execute("SELECT * FROM shots WHERE id=?", (db_id,)).fetchone()
        if row is None:
            raise ValueError("Shot not found")
        shot = _row_to_shot(row)
        shot.manual_tags = self._tags.manual_names(db_id)
        shot.automatic_tags = self._tags.automatic_names(db_id)
        shot.tags = sorted(set(shot.manual_tags + shot.automatic_tags))
        return shot

    def delete_shot(self, shot_id: str, project_id: int) -> bool:
        return self._shots.delete(shot_id, project_id)

    # Tag operations
    def set_manual_tags_by_id(self, db_id: int, tag_names: list[str]) -> bool:
        if self._shots.get_by_id(db_id) is None:
            return False
        self._tags.set_shot_tags(db_id, tag_names)
        return True

    def _tag_target(self, project_id: int, shot_id: str) -> LibraryShot | None:
        matches = [shot for shot in self._current_shots(project_id) if shot.shot_id == shot_id]
        # Before current-set markers existed, duplicate labels targeted the latest row.
        return max(matches, key=lambda shot: shot.id, default=None)

    def tag_shot(self, project_id: int, shot_id: str, tag_name: str) -> bool:
        shot = self._tag_target(project_id, shot_id)
        if shot is None:
            return False
        self._tags.add_shot_tag(shot.id, tag_name)
        return True

    def untag_shot(self, project_id: int, shot_id: str, tag_name: str) -> bool:
        shot = self._tag_target(project_id, shot_id)
        if shot is None:
            return False
        return self._tags.remove_shot_tag(shot.id, tag_name)

    def set_shot_tags(self, project_id: int, shot_id: str, tag_names: list[str]) -> bool:
        shot = self._tag_target(project_id, shot_id)
        if shot is None:
            return False
        self._tags.set_shot_tags(shot.id, tag_names)
        return True

    def list_tags(self) -> list[Any]:
        return self._tags.list_all()

    # Search / filters
    def search(self, filters: FilterSet) -> list[LibraryShot]:
        return self._search.search(filters)

    def unique_motion_types(self) -> list[str]:
        return self._search.get_unique_motion_types()


class ProjectRepository:
    """Repository for Project persistence."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _row_to_project(self, row: Any) -> LibraryProject:
        return LibraryProject(
            id=row["id"],
            name=row["name"],
            video_path=str(resolve_path(row["video_path"])) if row["video_path"] else None,
            video_filename=row["video_filename"] or "",
            video_duration=row["video_duration"] or 0.0,
            video_width=row["video_width"] or 0,
            video_height=row["video_height"] or 0,
            video_fps=row["video_fps"] or 0.0,
            video_codec=row["video_codec"] or "",
            analysis_status=row["analysis_status"] or "idle",
            analysis_message=row["analysis_message"] or "",
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            video_hash=row["video_hash"],
            assets_dir=row["assets_dir"],
            audio=json.loads(row["audio_json"] or "{}"),
            rhythm_summary=json.loads(row["rhythm_summary_json"] or "{}"),
            video_has_audio=bool(row["video_has_audio"]),
            display_name=(row["display_name"] or row["name"])
            if "display_name" in row.keys()
            else row["name"],
            last_opened_at=row["last_opened_at"] or "" if "last_opened_at" in row.keys() else "",
        )

    def upsert_from_pydantic(self, project: Any, commit: bool = True) -> int:
        data = project.model_dump() if hasattr(project, "model_dump") else dict(project)
        video = data.get("video") or {}
        name = data.get("project_name", "untitled")
        source = data.get("video_path")
        path = resolve_path(source)
        captured = data.get("source_hash") or None
        if captured is not None:
            if not isinstance(captured, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', captured):
                raise ValueError("已验证的视频内容身份无效，请重新导入")
            captured = captured.lower()
        known_id = data.get("library_project_id")
        if known_id is not None:
            known = self.get(known_id)
            if known is None:
                raise ValueError("已保存项目不存在，请重新打开项目")
            if captured is not None and captured != known.video_hash:
                raise SourceIdentityMismatch("分析来源与已保存项目不一致，请重新导入为新项目，旧分析保持原样")
            if (
                path
                and path.is_file()
                and known.video_hash
                and not known.video_hash.startswith("legacy:")
            ):
                if video_hash(path) != known.video_hash:
                    raise SourceIdentityMismatch("源视频内容已改变，请重新导入为新项目，旧分析保持原样")
            if captured and video and path and path.is_file():
                self._conn.execute(
                    "UPDATE projects SET video_width=?,video_height=?,video_duration=?,video_fps=? WHERE id=?",
                    (video['width'], video['height'], video['duration'], video['fps'], known_id),
                )
                self._conn.execute("UPDATE videos SET metadata_json=? WHERE content_hash=?",
                                   (json.dumps(video), captured))
            # Update the exact persisted identity even if the original file disappeared.
            # Never create a legacy hash/new row for an already-saved project.
            self._conn.execute(
                "UPDATE projects SET video_path=?,analysis_status=?,analysis_message=?,assets_dir=?,audio_json=?,rhythm_summary_json=?,updated_at=datetime('now') WHERE id=?",
                (
                    store_path(source),
                    data.get("analysis_status", "idle"),
                    data.get("analysis_message", ""),
                    store_path(data.get("assets_dir") or known.assets_dir),
                    json.dumps(data.get("audio", {}), ensure_ascii=False),
                    json.dumps(data.get("rhythm_summary", {}), ensure_ascii=False),
                    known_id,
                ),
            )
            if commit:
                self._conn.commit()
            return known_id
        digest = video_hash(path) if path and path.is_file() else None
        if captured is not None and digest is not None and digest != captured:
            raise SourceIdentityMismatch("源视频内容已改变，请重新导入为新项目，旧分析保持原样")
        # A missing file does not erase the identity verified during analysis.
        # Only historical objects without that evidence need a legacy identity.
        identity = captured or digest or "legacy:" + hashlib.sha256(f"{name}:{source}".encode()).hexdigest()
        self._conn.execute(
            """INSERT INTO videos(content_hash,source_path,metadata_json) VALUES (?,?,?)
            ON CONFLICT(content_hash) DO UPDATE SET source_path=excluded.source_path,metadata_json=excluded.metadata_json""",
            (identity, store_path(source) or "", json.dumps(video)),
        )
        vid = self._conn.execute(
            "SELECT id FROM videos WHERE content_hash=?", (identity,)
        ).fetchone()[0]
        existing = self._conn.execute(
            "SELECT id,name FROM projects WHERE video_hash=?", (identity,)
        ).fetchone()
        if existing:
            name = existing["name"]
        else:
            same_name = self.get_by_name(name)
            if same_name and same_name.video_hash is None and same_name.video_path == str(path):
                self._conn.execute(
                    "UPDATE projects SET video_hash=? WHERE id=?", (identity, same_name.id)
                )
            elif same_name:
                name = f"{name}_{hashlib.sha256(identity.encode()).hexdigest()[:8]}"
        self._conn.execute(
            """
            INSERT INTO projects (
                name, video_path, video_filename, video_duration, video_width,
                video_height, video_fps, video_codec, analysis_status, analysis_message,
                video_hash, assets_dir, video_id, audio_json, rhythm_summary_json, video_has_audio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                video_path = excluded.video_path,
                video_filename = excluded.video_filename,
                video_duration = excluded.video_duration,
                video_width = excluded.video_width,
                video_height = excluded.video_height,
                video_fps = excluded.video_fps,
                video_codec = excluded.video_codec,
                analysis_status = excluded.analysis_status,
                analysis_message = excluded.analysis_message,
                video_hash = excluded.video_hash,
                assets_dir = excluded.assets_dir,
                video_id = excluded.video_id,
                audio_json = excluded.audio_json,
                rhythm_summary_json = excluded.rhythm_summary_json,
                video_has_audio = excluded.video_has_audio,
                updated_at = datetime('now')
            """,
            (
                name,
                store_path(source),
                video.get("filename", ""),
                video.get("duration", 0.0),
                video.get("width", 0),
                video.get("height", 0),
                video.get("fps", 0.0),
                video.get("codec", ""),
                data.get("analysis_status", "idle"),
                data.get("analysis_message", ""),
                identity,
                store_path(
                    data.get("assets_dir") or ROOT / "output" / data.get("project_name", "untitled")
                ),
                vid,
                json.dumps(data.get("audio", {}), ensure_ascii=False),
                json.dumps(data.get("rhythm_summary", {}), ensure_ascii=False),
                video.get("has_audio", False),
            ),
        )
        if commit:
            self._conn.commit()
        return self._conn.execute(
            "SELECT id FROM projects WHERE video_hash=?", (identity,)
        ).fetchone()[0]

    def get(self, project_id: int) -> LibraryProject | None:
        row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def get_by_name(self, name: str) -> LibraryProject | None:
        row = self._conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def list_all(self) -> list[LibraryProject]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def delete(self, project_id: int) -> bool:
        cursor = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()
        return cursor.rowcount > 0
