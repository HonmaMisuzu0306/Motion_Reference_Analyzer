"""Regression tests for library identity, transaction isolation and legacy portability."""
import json
import sqlite3
from pathlib import Path
from threading import Event, Thread

import pytest

from db import ReferenceLibrary
from db.connection import close_connection, set_db_path
from db.models import FilterSet
from db.paths import resolve_path
from db.schema import CREATE_SCHEMA_SQL
from schemas import Project, Shot, TimeRange


@pytest.fixture
def library(tmp_path):
    set_db_path(tmp_path / 'library.db')
    lib = ReferenceLibrary()
    yield lib
    close_connection()


def make_shot(start=0, end=1, version='v1'):
    return Shot(shot_id='shot_001', time=TimeRange(start=start, end=end, duration=end-start),
                analysis_version=version, observations={'description': version})


def test_identity_preserves_versions_ranges_and_manual_tag_owner(library, tmp_path):
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'video')
    pid = library.save_project(Project(project_name='sample', video_path=str(source)))
    first = library.save_shot(make_shot(), pid)
    library.tag_shot(pid, 'shot_001', 'favorite')
    second = library.save_shot(make_shot(version='v2'), pid)
    third = library.save_shot(make_shot(start=4, end=5, version='v2'), pid)
    assert len({first, second, third}) == 3
    assert library.get_shot(first).manual_tags == ['favorite']
    assert library.get_shot(second).manual_tags == []
    assert library.get_shot(third).manual_tags == []
    assert library.set_manual_tags_by_id(second, ['v2-review'])
    assert library.get_shot(first).manual_tags == ['favorite']
    assert library.get_shot(second).manual_tags == ['v2-review']
    assert library.get_shot(third).manual_tags == []
    assert library.save_shot(make_shot(version='v2'), pid) == second


def test_concurrent_tag_commit_cannot_commit_failed_analysis(library, tmp_path, monkeypatch):
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'video')
    saved = Event()
    release = Event()
    tag_done = Event()
    failures = []
    real_save = library.save_shot

    def save_then_fail(shot, pid, commit=True):
        real_save(shot, pid, commit)
        saved.set()
        assert release.wait(3)
        raise RuntimeError('simulated storage failure')

    monkeypatch.setattr(library, 'save_shot', save_then_fail)

    def save_analysis():
        try:
            library.save_analysis(Project(project_name='partial', video_path=str(source),
                                          shots=[make_shot()]))
        except RuntimeError as exc:
            failures.append(str(exc))
        finally:
            close_connection()

    def save_tag():
        try:
            library._tags.ensure('independent-tag')
            tag_done.set()
        finally:
            close_connection()

    writer = Thread(target=save_analysis)
    tagger = Thread(target=save_tag)
    writer.start()
    assert saved.wait(3)
    tagger.start()
    tag_done.wait(.3)
    release.set()
    writer.join(3)
    tagger.join(3)
    assert not writer.is_alive() and not tagger.is_alive()
    assert failures == ['simulated storage failure']
    assert library.list_projects() == []
    assert [tag.name for tag in library.list_tags()] == ['independent-tag']


@pytest.mark.parametrize('version', [0, 2])
def test_legacy_migration_keeps_data_tags_and_portable_assets(tmp_path, monkeypatch, version):
    import db.library as library_module
    import db.paths as paths

    old_root = tmp_path / 'old'
    old_root.mkdir()
    source = old_root / 'samples' / 'video.mp4'
    source.parent.mkdir()
    source.write_bytes(b'video')
    frame = old_root / 'output' / 'legacy' / 'shots' / 'shot_001' / 'frame_01.jpg'
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b'image')
    db_path = old_root / 'library.db'
    with sqlite3.connect(db_path) as conn:
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
        conn.execute('INSERT INTO projects(id,name,video_path) VALUES (7,?,?)', ('legacy', str(source)))
        conn.execute('INSERT INTO shots(id,project_id,shot_id,frame_paths,thumbnail_path,typography,observations) '
                     'VALUES (9,7,?,?,?,?,?)', ('shot_001', json.dumps(['frame_01.jpg']),
                     'frame_01.jpg', '{"has_text":true}', '{"description":"legacy evidence"}'))
        conn.execute("INSERT INTO tags(id,name) VALUES (4,'favorite')")
        conn.execute('INSERT INTO shot_tags VALUES (9,4)')
        conn.execute(f'PRAGMA user_version={version}')
    conn.close()
    monkeypatch.setattr(paths, 'ROOT', old_root)
    monkeypatch.setattr(library_module, 'ROOT', old_root)
    set_db_path(db_path)
    lib = ReferenceLibrary()
    assert lib.get_shot(9).manual_tags == ['favorite']
    assert [s.id for s in lib.search(FilterSet(query='legacy', has_text=True, tags=['favorite', 'typography']))] == [9]
    assert lib.save_project(Project(project_name='reimport_hash_name', video_path=str(source))) == 7
    close_connection()
    new_root = tmp_path / 'moved'
    old_root.rename(new_root)
    monkeypatch.setattr(paths, 'ROOT', new_root)
    monkeypatch.setattr(library_module, 'ROOT', new_root)
    set_db_path(new_root / 'library.db')
    reopened = ReferenceLibrary()
    assert Path(reopened.get_project(7).video_path).read_bytes() == b'video'
    assert resolve_path(reopened.get_shot(9).thumbnail_path).read_bytes() == b'image'
    assert reopened.get_shot(9).manual_tags == ['favorite']
    newer = make_shot(version='new-version')
    assert reopened.save_shot(newer, 7) != 9
    assert reopened.get_shot(9).observations == {'description': 'legacy evidence'}
    assert reopened._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    close_connection()


def test_legacy_duplicate_identity_keeps_both_payloads_and_tag_ids(tmp_path):
    db_path = tmp_path / 'duplicates.db'
    conn = sqlite3.connect(db_path)
    conn.executescript(CREATE_SCHEMA_SQL)
    conn.execute("INSERT INTO projects(id,name) VALUES (7,'legacy')")
    conn.execute("INSERT INTO shots(id,project_id,shot_id,start_time,end_time,observations) "
                 "VALUES (9,7,'first',0,1,'{\"description\":\"first\"}')")
    conn.execute("INSERT INTO shots(id,project_id,shot_id,start_time,end_time,observations) "
                 "VALUES (10,7,'second',0,1,'{\"description\":\"second\"}')")
    conn.execute("INSERT INTO tags(id,name) VALUES (4,'favorite')")
    conn.execute('INSERT INTO shot_tags VALUES (10,4)')
    conn.commit()
    conn.close()
    set_db_path(db_path)
    lib = ReferenceLibrary()
    assert lib.get_shot(9).observations == {'description': 'first'}
    assert lib.get_shot(10).observations == {'description': 'second'}
    assert lib.get_shot(10).manual_tags == ['favorite']
    assert len(lib.list_shots(7)) == 2
    close_connection()
