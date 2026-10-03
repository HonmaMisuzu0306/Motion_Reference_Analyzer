"""Tag CRUD and shot/project associations."""

from __future__ import annotations

from db.connection import get_sqlite_connection
from db.models import Tag


class TagRepository:
    """Repository for tags and many-to-many associations."""

    def __init__(self) -> None:
        self._conn = get_sqlite_connection()

    def ensure(self, name: str, color: str = "#3b82f6", commit: bool = True) -> Tag:
        """Create tag if missing and return it."""
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)",
            (name, color),
        )
        if commit:
            self._conn.commit()
        return self.get_by_name(name) or Tag(id=cursor.lastrowid or 0, name=name, color=color)

    def get_by_name(self, name: str) -> Tag | None:
        row = self._conn.execute(
            "SELECT * FROM tags WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return Tag(id=row["id"], name=row["name"], color=row["color"], created_at=row["created_at"])

    def get_by_id(self, tag_id: int) -> Tag | None:
        row = self._conn.execute(
            "SELECT * FROM tags WHERE id = ?", (tag_id,)
        ).fetchone()
        if row is None:
            return None
        return Tag(id=row["id"], name=row["name"], color=row["color"], created_at=row["created_at"])

    def list_all(self) -> list[Tag]:
        rows = self._conn.execute(
            "SELECT * FROM tags ORDER BY name ASC"
        ).fetchall()
        return [Tag(id=r["id"], name=r["name"], color=r["color"], created_at=r["created_at"]) for r in rows]

    def delete(self, tag_id: int) -> bool:
        cursor = self._conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def get_shot_tags(self, shot_db_id: int) -> list[Tag]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT t.* FROM tags t
            JOIN (SELECT tag_id FROM shot_tags WHERE shot_id=?
                  UNION SELECT tag_id FROM automatic_shot_tags WHERE shot_id=?) st ON st.tag_id = t.id
            ORDER BY t.name ASC
            """,
            (shot_db_id, shot_db_id),
        ).fetchall()
        return [Tag(id=r["id"], name=r["name"], color=r["color"], created_at=r["created_at"]) for r in rows]

    def automatic_names(self, shot_id: int) -> list[str]:
        return [r[0] for r in self._conn.execute(
            "SELECT t.name FROM tags t JOIN automatic_shot_tags a ON a.tag_id=t.id WHERE a.shot_id=? ORDER BY t.name",
            (shot_id,))]

    def manual_names(self, shot_id: int) -> list[str]:
        return [r[0] for r in self._conn.execute(
            "SELECT t.name FROM tags t JOIN shot_tags a ON a.tag_id=t.id WHERE a.shot_id=? ORDER BY t.name",
            (shot_id,))]

    def refresh_automatic(self, shot_id: int, names: set[str]) -> None:
        self._conn.execute("DELETE FROM automatic_shot_tags WHERE shot_id=?", (shot_id,))
        for name in sorted(names):
            tag = self.ensure(name, commit=False)
            self._conn.execute("INSERT INTO automatic_shot_tags VALUES (?,?)", (shot_id, tag.id))

    def set_shot_tags(self, shot_db_id: int, tag_names: list[str]) -> None:
        """Replace all tags for a shot."""
        with self._conn:
            self._conn.execute("DELETE FROM shot_tags WHERE shot_id = ?", (shot_db_id,))
            for name in set(tag_names):
                tag = self.ensure(name, commit=False)
                self._conn.execute(
                    "INSERT OR IGNORE INTO shot_tags (shot_id, tag_id) VALUES (?, ?)",
                    (shot_db_id, tag.id),
                )

    def add_shot_tag(self, shot_db_id: int, tag_name: str) -> None:
        tag = self.ensure(tag_name)
        self._conn.execute(
            "INSERT OR IGNORE INTO shot_tags (shot_id, tag_id) VALUES (?, ?)",
            (shot_db_id, tag.id),
        )
        self._conn.commit()

    def remove_shot_tag(self, shot_db_id: int, tag_name: str) -> bool:
        tag = self.get_by_name(tag_name)
        if tag is None:
            return False
        cursor = self._conn.execute(
            "DELETE FROM shot_tags WHERE shot_id = ? AND tag_id = ?",
            (shot_db_id, tag.id),
        )
        self._conn.commit()
        return cursor.rowcount > 0
