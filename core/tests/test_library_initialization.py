"""Concurrent first reads must initialize/migrate the Library exactly once."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from app import api
from db.connection import close_connection, set_db_path
from db.schema import CREATE_SCHEMA_SQL
from schemas.library import FilterRequest


@pytest.mark.parametrize('version', [None, 0, 2])
def test_concurrent_first_reads_initialize_one_library(tmp_path, monkeypatch, version):
    db_path = tmp_path / 'first_reads.db'
    if version is not None:
        conn = sqlite3.connect(db_path)
        conn.executescript(CREATE_SCHEMA_SQL)
        if version == 2:
            for column in ['video_hash TEXT', 'assets_dir TEXT', 'video_id INTEGER']:
                conn.execute('ALTER TABLE projects ADD COLUMN ' + column)
            for column in ['motion_confidence REAL DEFAULT 0', "scene_type TEXT DEFAULT ''",
                           "analysis_version TEXT DEFAULT 'mra-analysis-v1'",
                           "pipeline_version TEXT DEFAULT 'mra-pipeline-v1'",
                           "provider_versions TEXT DEFAULT '{}'" ]:
                conn.execute('ALTER TABLE shots ADD COLUMN ' + column)
            conn.executescript("""CREATE TABLE videos(id INTEGER PRIMARY KEY,content_hash TEXT UNIQUE,
                source_path TEXT,metadata_json TEXT); CREATE TABLE automatic_shot_tags(
                shot_id INTEGER REFERENCES shots(id) ON DELETE CASCADE,
                tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,PRIMARY KEY(shot_id,tag_id));""")
        conn.execute("INSERT INTO projects(name) VALUES ('legacy')")
        conn.executemany('INSERT INTO shots(project_id,shot_id,start_time,end_time) VALUES (1,?,?,?)',
                         [(f'shot_{n}', n, n+1) for n in range(1000)])
        conn.execute(f'PRAGMA user_version={version}')
        conn.commit()
        conn.close()
    set_db_path(db_path)
    api.reset_library()
    constructor = api.ReferenceLibrary
    attempts = []
    attempt_lock = Lock()

    def audited_constructor():
        with attempt_lock:
            attempts.append(1)
        return constructor()

    monkeypatch.setattr(api, 'ReferenceLibrary', audited_constructor)
    gate = Barrier(8)

    def first_read(index):
        gate.wait()
        try:
            if index % 3 == 0:
                return api.list_library_projects()
            if index % 3 == 1:
                return api.list_tags()
            return api.search_library(FilterRequest(limit=1))
        finally:
            close_connection()

    with ThreadPoolExecutor(8) as workers:
        results = list(workers.map(first_read, range(8)))
    assert len(attempts) == 1
    expected_count = 0 if version is None else 1
    assert len(results[0]['projects']) == expected_count
    assert len(results[2]['shots']) == expected_count
    assert results[1]['tags'] == []
    api.reset_library()
