"""Search and filtering for the Reference Library."""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from db.connection import get_sqlite_connection
from db.models import FilterSet, LibraryShot
from db.shots import _row_to_shot
from db.tags import TagRepository

logger = logging.getLogger(__name__)


def _fts5_enabled(conn: sqlite3.Connection) -> bool:
    """Check whether the shots_fts virtual table exists."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='shots_fts'"
    ).fetchone()
    return row is not None


class SearchRepository:
    """Search and filter shots across projects."""

    def __init__(self) -> None:
        self._conn = get_sqlite_connection()
        self._fts5 = _fts5_enabled(self._conn)
        self._tags = TagRepository()

    def search(self, filters: FilterSet) -> list[LibraryShot]:
        params: list[Any] = []
        conditions: list[str] = ["1=1"]

        # FTS5 query
        if filters.query and self._fts5:
            conditions.append(
                "s.id IN (SELECT rowid FROM shots_fts WHERE shots_fts MATCH ?)"
            )
            tokens = re.findall(r'\w+', filters.query, re.UNICODE)
            if not tokens:
                return []
            params.append(' AND '.join('"' + token.replace('"', '""') + '"' for token in tokens))
        elif filters.query:
            # Fallback to LIKE on key JSON/text columns
            like = f"%{filters.query}%"
            conditions.append(
                "(s.shot_id LIKE ? OR s.observations LIKE ? OR s.motion_type LIKE ? OR s.text_regions LIKE ? OR s.typography_tracks LIKE ?)"
            )
            params.extend([like, like, like, like, like])

        if filters.motion_types:
            placeholders = ",".join("?" for _ in filters.motion_types)
            conditions.append(f"s.motion_type IN ({placeholders})")
            params.extend(filters.motion_types)

        if filters.has_text is not None:
            conditions.append("s.has_text = ?")
            params.append(1 if filters.has_text else 0)

        if filters.min_duration is not None:
            conditions.append("s.duration >= ?")
            params.append(filters.min_duration)

        if filters.max_duration is not None:
            conditions.append("s.duration <= ?")
            params.append(filters.max_duration)

        if filters.tags:
            placeholders = ",".join("?" for _ in filters.tags)
            conditions.append(
                f"""
                s.id IN (
                    SELECT st.shot_id FROM (
                        SELECT shot_id,tag_id FROM shot_tags
                        UNION SELECT shot_id,tag_id FROM automatic_shot_tags
                    ) st JOIN tags t ON t.id=st.tag_id
                    WHERE t.name IN ({placeholders})
                    GROUP BY st.shot_id
                    HAVING COUNT(DISTINCT t.name) = ?
                )
                """
            )
            names = sorted(set(filters.tags))
            # Input duplicates represent the same label.
            params.extend(filters.tags)
            params.append(len(names))

        if filters.project_id is not None:
            conditions.append("s.project_id = ?")
            params.append(filters.project_id)
        if filters.min_confidence is not None:
            conditions.append("s.motion_confidence >= ?")
            params.append(filters.min_confidence)
        if filters.max_confidence is not None:
            conditions.append("s.motion_confidence <= ?")
            params.append(filters.max_confidence)
        where_sql = " AND ".join(conditions)

        sql = f"""
            SELECT DISTINCT s.* FROM shots s
            WHERE {where_sql}
            ORDER BY s.project_id DESC, s.start_time ASC, s.id ASC
            LIMIT ? OFFSET ?
        """
        params.append(filters.limit)
        params.append(filters.offset)

        rows = self._conn.execute(sql, params).fetchall()
        shots = [_row_to_shot(row) for row in rows]
        # Populate tags for each shot
        for shot in shots:
            shot.tags = [t.name for t in self._tags.get_shot_tags(shot.id)]
            shot.manual_tags = self._tags.manual_names(shot.id)
            shot.automatic_tags = self._tags.automatic_names(shot.id)
        return shots

    def get_unique_motion_types(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT motion_type FROM shots WHERE motion_type != '' ORDER BY motion_type"
        ).fetchall()
        return [r["motion_type"] for r in rows]
