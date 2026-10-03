"""SQLite connection management."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH: Path | None = None
_LOCAL = threading.local()


def set_db_path(path: Path) -> None:
    """Set the global SQLite database file path."""
    global _DB_PATH
    close_connection()
    _DB_PATH = path


def get_db_path() -> Path:
    """Return the configured SQLite database file path."""
    global _DB_PATH
    if _DB_PATH is None:
        from app.runtime_paths import get_runtime_paths
        _DB_PATH = get_runtime_paths().database
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def get_sqlite_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection with row factory."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = getattr(_LOCAL, "conn", None)
    if conn is not None and getattr(_LOCAL, "path", None) != db_path:
        close_connection()
        conn = None
    if conn is None:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        _LOCAL.conn = conn
        _LOCAL.path = db_path
    return conn


def close_connection() -> None:
    """Close the thread-local connection if open."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        conn.close()
        _LOCAL.conn = None
