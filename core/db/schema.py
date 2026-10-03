"""SQLite schema for Reference Library."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    video_path TEXT,
    video_filename TEXT,
    video_duration REAL DEFAULT 0,
    video_width INTEGER DEFAULT 0,
    video_height INTEGER DEFAULT 0,
    video_fps REAL DEFAULT 0,
    video_codec TEXT DEFAULT '',
    analysis_status TEXT DEFAULT 'idle',
    analysis_message TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    shot_id TEXT NOT NULL,
    start_time REAL DEFAULT 0,
    end_time REAL DEFAULT 0,
    duration REAL DEFAULT 0,
    thumbnail_path TEXT,
    frame_paths TEXT DEFAULT '[]',
    observations TEXT DEFAULT '{}',
    motion TEXT DEFAULT '{}',
    measured_motion TEXT DEFAULT '{}',
    motion_summary TEXT DEFAULT '{}',
    typography TEXT DEFAULT '{}',
    text_regions TEXT DEFAULT '[]',
    typography_tracks TEXT DEFAULT '[]',
    ae_hypothesis TEXT DEFAULT '{}',
    ae_recipe TEXT DEFAULT '{}',
    visual_effects TEXT DEFAULT '[]',
    analysis_error TEXT DEFAULT '',
    has_text INTEGER DEFAULT 0,
    motion_type TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, shot_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT DEFAULT '#3b82f6',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shot_tags (
    shot_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (shot_id, tag_id),
    FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_tags (
    project_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (project_id, tag_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
"""

FTS5_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS shots_fts USING fts5(
    shot_id,
    observations,
    motion_type,
    text_regions,
    typography_tracks,
    content='shots',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS shots_fts_insert AFTER INSERT ON shots BEGIN
    INSERT INTO shots_fts(rowid, shot_id, observations, motion_type, text_regions, typography_tracks)
    VALUES (new.id, new.shot_id, new.observations, new.motion_type, new.text_regions, new.typography_tracks);
END;

CREATE TRIGGER IF NOT EXISTS shots_fts_delete AFTER DELETE ON shots BEGIN
    INSERT INTO shots_fts(shots_fts, rowid, shot_id, observations, motion_type, text_regions, typography_tracks)
    VALUES ('delete', old.id, old.shot_id, old.observations, old.motion_type, old.text_regions, old.typography_tracks);
END;

CREATE TRIGGER IF NOT EXISTS shots_fts_update AFTER UPDATE ON shots BEGIN
    INSERT INTO shots_fts(shots_fts, rowid, shot_id, observations, motion_type, text_regions, typography_tracks)
    VALUES ('delete', old.id, old.shot_id, old.observations, old.motion_type, old.text_regions, old.typography_tracks);
    INSERT INTO shots_fts(rowid, shot_id, observations, motion_type, text_regions, typography_tracks)
    VALUES (new.id, new.shot_id, new.observations, new.motion_type, new.text_regions, new.typography_tracks);
END;
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_shots_project ON shots(project_id);
CREATE INDEX IF NOT EXISTS idx_shots_time ON shots(start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_shots_motion ON shots(motion_type);
CREATE INDEX IF NOT EXISTS idx_shots_has_text ON shots(has_text);
"""


def _fts5_available(conn: sqlite3.Connection) -> bool:
    """Check whether SQLite was compiled with FTS5 support."""
    try:
        conn.execute("CREATE VIRTUAL TABLE __fts5_test USING fts5(text)")
        conn.execute("DROP TABLE __fts5_test")
        return True
    except sqlite3.Error:
        return False


def _migrate_identity_and_assets(conn: sqlite3.Connection) -> None:
    """Rebuild the old UNIQUE(project_id, shot_id) table without losing row IDs."""
    from db.automatic_tags import automatic_tags
    from db.paths import ROOT, resolve_path, store_path, video_hash
    from db.shots import _json_loads, _row_to_shot

    conn.commit()
    foreign_keys = conn.execute('PRAGMA foreign_keys').fetchone()[0]
    previous_factory = conn.row_factory
    conn.execute('PRAGMA foreign_keys=OFF')
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.execute('BEGIN')
            definition = conn.execute("SELECT sql FROM sqlite_master WHERE name='shots'").fetchone()[0]
            definition = 'CREATE TABLE shots_v3 (' + definition.split('(', 1)[1]
            definition = re.sub(r'UNIQUE\s*\(\s*project_id\s*,\s*shot_id\s*\)',
                                'UNIQUE(project_id,start_time,end_time,analysis_version)',
                                definition, flags=re.IGNORECASE)
            conn.execute(definition)
            # Older libraries could store two labels for the same time range.
            # Retain both evidence records and tag IDs; archive extra records
            # under a distinct legacy version, recording their original version.
            duplicates = conn.execute('SELECT * FROM (SELECT *,ROW_NUMBER() OVER '
                                      '(PARTITION BY project_id,start_time,end_time,analysis_version ORDER BY id) '
                                      'AS ordinal FROM shots) WHERE ordinal>1').fetchall()
            for duplicate in duplicates:
                archived_version = f"{duplicate['analysis_version']}:legacy-duplicate:{duplicate['id']}"
                providers = _json_loads(duplicate['provider_versions'], {})
                providers['legacy_analysis_version'] = duplicate['analysis_version']
                conn.execute('UPDATE shots SET analysis_version=?,provider_versions=? WHERE id=?',
                             (archived_version, json.dumps(providers), duplicate['id']))
            columns = [row[1] for row in conn.execute('PRAGMA table_info(shots)')]
            names = ','.join('"' + name + '"' for name in columns)
            conn.execute(f'INSERT INTO shots_v3 ({names}) SELECT {names} FROM shots')
            conn.execute('DROP TABLE shots')
            conn.execute('ALTER TABLE shots_v3 RENAME TO shots')

            for project in conn.execute('SELECT * FROM projects').fetchall():
                source = resolve_path(project['video_path'])
                assets = store_path(project['assets_dir'] or ROOT / 'output' / project['name'])
                digest = project['video_hash']
                if not digest and source and source.is_file():
                    digest = video_hash(source)
                video_id = project['video_id']
                if digest:
                    metadata = {name.removeprefix('video_'): project[name] for name in
                                ['video_filename', 'video_duration', 'video_width', 'video_height',
                                 'video_fps', 'video_codec']}
                    conn.execute('INSERT INTO videos(content_hash,source_path,metadata_json) VALUES (?,?,?) '
                                 'ON CONFLICT(content_hash) DO NOTHING',
                                 (digest, store_path(project['video_path']) or '', json.dumps(metadata)))
                    video_id = conn.execute('SELECT id FROM videos WHERE content_hash=?', (digest,)).fetchone()[0]
                    # Keep duplicate historical projects and their data, using the
                    # first hash owner for future imports instead of deleting rows.
                    owner = conn.execute('SELECT id FROM projects WHERE video_hash=? AND id!=?',
                                         (digest, project['id'])).fetchone()
                    if owner:
                        digest = None
                conn.execute('UPDATE projects SET video_path=?,assets_dir=?,video_hash=?,video_id=? WHERE id=?',
                             (store_path(project['video_path']), assets, digest, video_id, project['id']))

            for row in conn.execute('SELECT s.*,p.assets_dir FROM shots s JOIN projects p ON p.id=s.project_id').fetchall():
                def portable_frame(value):
                    if not value:
                        return None
                    path = Path(value)
                    if not path.is_absolute() and len(path.parts) == 1:
                        path = ROOT / row['assets_dir'] / 'shots' / row['shot_id'] / path
                    return store_path(path)

                frames = [portable_frame(value) for value in _json_loads(row['frame_paths'], [])]
                thumbnail = portable_frame(row['thumbnail_path']) or (frames[0] if frames else None)
                typography = _json_loads(row['typography'], {})
                regions = _json_loads(row['text_regions'], [])
                tracks = _json_loads(row['typography_tracks'], [])
                motion = _json_loads(row['motion'], {})
                summary = _json_loads(row['motion_summary'], {})
                observations = _json_loads(row['observations'], {})
                conn.execute('UPDATE shots SET thumbnail_path=?,frame_paths=?,has_text=?,motion_confidence=?,scene_type=? WHERE id=?',
                             (thumbnail, json.dumps(frames, ensure_ascii=False),
                              bool(typography.get('has_text') or regions or tracks),
                              summary.get('fused_confidence', motion.get('confidence', 0)),
                              observations.get('scene_type', ''), row['id']))
                stored = conn.execute('SELECT * FROM shots WHERE id=?', (row['id'],)).fetchone()
                conn.execute('DELETE FROM automatic_shot_tags WHERE shot_id=?', (row['id'],))
                for label in automatic_tags(_row_to_shot(stored)):
                    conn.execute('INSERT OR IGNORE INTO tags(name) VALUES (?)', (label,))
                    tag_id = conn.execute('SELECT id FROM tags WHERE name=?', (label,)).fetchone()[0]
                    conn.execute('INSERT INTO automatic_shot_tags VALUES (?,?)', (row['id'], tag_id))
            conn.execute('PRAGMA user_version=3')
    finally:
        conn.row_factory = previous_factory
        conn.execute(f'PRAGMA foreign_keys={foreign_keys}')


def init_schema(conn: sqlite3.Connection | None = None) -> bool:
    """Initialize database schema. Returns True if FTS5 was enabled."""
    if conn is None:
        from db.connection import get_db_path

        conn = sqlite3.connect(str(get_db_path()))
        own = True
    else:
        own = False

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > 6:
        raise ValueError(f"Unsupported future library schema: {version}")
    conn.executescript(CREATE_SCHEMA_SQL)
    if version < 2:
        # Additive migration preserves IDs, associations, JSON and all source files.
        additions = {
            "projects": {"video_hash": "TEXT", "assets_dir": "TEXT", "video_id": "INTEGER"},
            "shots": {"motion_confidence": "REAL DEFAULT 0", "scene_type": "TEXT DEFAULT ''",
                      "analysis_version": "TEXT DEFAULT 'mra-analysis-v1'",
                      "pipeline_version": "TEXT DEFAULT 'mra-pipeline-v1'",
                      "provider_versions": "TEXT DEFAULT '{}'"},
        }
        for table, columns in additions.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, declaration in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY, content_hash TEXT NOT NULL UNIQUE,
                source_path TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS automatic_shot_tags (
                shot_id INTEGER NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY(shot_id, tag_id));
            CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_hash ON projects(video_hash)
                WHERE video_hash IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_shots_duration ON shots(duration);
            CREATE INDEX IF NOT EXISTS idx_shots_confidence ON shots(motion_confidence);
            CREATE INDEX IF NOT EXISTS idx_shots_identity ON shots(project_id,start_time,end_time,analysis_version);
        """)
        conn.execute("""UPDATE shots SET motion_confidence=COALESCE(
            json_extract(motion_summary,'$.fused_confidence'),json_extract(motion,'$.confidence'),0),
            scene_type=COALESCE(json_extract(observations,'$.scene_type'),'')""")
    if version < 3:
        _migrate_identity_and_assets(conn)
    if version < 4:
        # Additive M6 migration. Never rebuild or discard historical shot identities.
        for table, columns in {
            'projects': {'audio_json': "TEXT DEFAULT '{}'", 'rhythm_summary_json': "TEXT DEFAULT '{}'",
                         'video_has_audio': 'INTEGER DEFAULT 0'},
            'shots': {'rhythm_json': "TEXT DEFAULT '{}'"},
        }.items():
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            for name, declaration in columns.items():
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
    if version < 5:
        existing={row[1] for row in conn.execute('PRAGMA table_info(projects)')}
        for name,declaration in {'display_name':"TEXT DEFAULT ''",'last_opened_at':"TEXT DEFAULT ''"}.items():
            if name not in existing:
                conn.execute(f'ALTER TABLE projects ADD COLUMN {name} {declaration}')
        conn.execute("UPDATE projects SET display_name=name WHERE display_name='' OR display_name IS NULL")
    conn.executescript(INDEXES_SQL)
    conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_hash ON projects(video_hash)
            WHERE video_hash IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_shots_duration ON shots(duration);
        CREATE INDEX IF NOT EXISTS idx_shots_confidence ON shots(motion_confidence);
        CREATE INDEX IF NOT EXISTS idx_shots_identity ON shots(project_id,start_time,end_time,analysis_version);
    """)

    fts5_enabled = _fts5_available(conn)
    if fts5_enabled:
        existed = conn.execute("SELECT 1 FROM sqlite_master WHERE name='shots_fts'").fetchone()
        conn.executescript(FTS5_SCHEMA_SQL)
        if not existed or version < 3:
            conn.execute("INSERT INTO shots_fts(shots_fts) VALUES ('rebuild')")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS selection_analyses (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('frame','clip')),
            source_hash TEXT NOT NULL,
            request_json TEXT NOT NULL,
            actual_time_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            progress_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'preparing'
                CHECK(status IN ('preparing','running','done','completed_with_warnings','error','interrupted')),
            assets_dir TEXT NOT NULL,
            versions_json TEXT NOT NULL DEFAULT '{}',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_selection_project_created
            ON selection_analyses(project_id,created_at DESC);
    """)
    definition = conn.execute("SELECT sql FROM sqlite_master WHERE name='selection_analyses'").fetchone()[0]
    if 'completed_with_warnings' not in definition:
        # Upgrade early schema-6 builds without touching the historical shot tables.
        with conn:
            conn.execute(definition.replace('selection_analyses', 'selection_analyses_new', 1)
                         .replace("'done','error'", "'done','completed_with_warnings','error'"))
            conn.execute('INSERT INTO selection_analyses_new SELECT * FROM selection_analyses')
            conn.execute('DROP TABLE selection_analyses')
            conn.execute('ALTER TABLE selection_analyses_new RENAME TO selection_analyses')
            conn.execute('CREATE INDEX idx_selection_project_created ON selection_analyses(project_id,created_at DESC)')
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    if own:
        conn.close()
    return fts5_enabled
