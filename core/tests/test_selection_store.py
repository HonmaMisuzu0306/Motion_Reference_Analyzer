"""Additive migration and worker records must never rewrite the existing library."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from db.schema import init_schema
from selection.store import SelectionStore


def database(path):
    with sqlite3.connect(path) as conn:
        init_schema(conn)
        conn.execute("INSERT INTO projects(id,name,video_path) VALUES(1,'原项目','source.mp4')")
        conn.execute("INSERT INTO projects(id,name,video_path) VALUES(2,'另一个','other.mp4')")
    return path


def test_additive_v5_migration_keeps_existing_rows_and_fk(tmp_path):
    path = database(tmp_path / 'library.sqlite')
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE IF EXISTS selection_analyses')
        conn.execute('PRAGMA user_version=5')
        before = conn.execute('SELECT * FROM projects').fetchall()
    store = SelectionStore(path)
    rid = store.create(1, 'clip', 'sha', {'start': 1, 'end': 4}, 'assets')
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 6
        assert conn.execute('SELECT * FROM projects').fetchall() == before
    assert store.get(rid)['request'] == {'start': 1, 'end': 4}
    with pytest.raises(sqlite3.IntegrityError):
        store.create(123, 'clip', 'sha', {}, 'assets')


def test_isolation_pagination_atomic_progress_and_recovery(tmp_path):
    store = SelectionStore(database(tmp_path / 'library.sqlite'))
    ids = [store.create(1, 'clip', 'sha', {}, 'assets') for _ in range(3)]
    store.create(2, 'frame', 'sha', {}, 'assets')
    assert store.list(1, limit=2)['total'] == 3
    assert len(store.list(1, limit=2, offset=2)['items']) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda i: store.update_progress(ids[0], 'vision', i, 3, '分析中'), range(3)))
    assert store.get(ids[0])['status'] == 'running'
    store.finish(ids[1], {'shots': []}, {'model': 'test'}, ['短片段'])
    assert store.recover_interrupted() == 3  # includes the other project preparing record
    assert store.get(ids[0])['status'] == 'interrupted'
    assert store.get(ids[1])['result'] == {'shots': []}
    with sqlite3.connect(store.database) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('DELETE FROM projects WHERE id=1')
    assert store.list(1)['total'] == 0
    assert store.list(2)['total'] == 1
    with pytest.raises(ValueError):
        store.list(2, limit=101)


def test_provider_partial_failure_is_visible_but_capability_note_is_not_failure(tmp_path):
    store = SelectionStore(database(tmp_path / 'library.sqlite'))
    partial = store.create(1, 'frame', 'sha', {}, 'assets')
    store.finish(partial, {'partial_failures': ['视觉推理失败']}, {}, ['视觉推理失败'])
    assert store.get(partial)['status'] == 'completed_with_warnings'
    normal = store.create(1, 'frame', 'sha', {}, 'assets')
    store.finish(normal, {'partial_failures': []}, {}, ['单帧无法判断运动'])
    assert store.get(normal)['status'] == 'done'


def test_early_schema6_status_constraint_upgrades_without_record_loss(tmp_path):
    path = database(tmp_path / 'library.sqlite')
    store = SelectionStore(path)
    rid = store.create(1, 'clip', 'sha', {}, 'assets')
    with sqlite3.connect(path) as conn:
        before = conn.execute('SELECT * FROM projects').fetchall()
        definition = conn.execute("SELECT sql FROM sqlite_master WHERE name='selection_analyses'").fetchone()[0]
        conn.execute(definition.replace('selection_analyses', 'old_selection', 1).replace("'completed_with_warnings',", ''))
        conn.execute('INSERT INTO old_selection SELECT * FROM selection_analyses')
        conn.execute('DROP TABLE selection_analyses')
        conn.execute('ALTER TABLE old_selection RENAME TO selection_analyses')
    upgraded = SelectionStore(path)
    upgraded.finish(rid, {'partial_failures': ['error']}, {}, ['error'])
    assert upgraded.get(rid)['status'] == 'completed_with_warnings'
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT * FROM projects').fetchall() == before


def test_record_list_is_a_summary_not_full_result(tmp_path):
    import sqlite3

    from selection.store import SelectionStore
    store = SelectionStore(tmp_path / 'library.db')
    with sqlite3.connect(store.database) as conn:
        pid = conn.execute("INSERT INTO projects(name) VALUES('summary')").lastrowid
    rid = store.create(pid, 'clip', 'hash', {'kind': 'clip', 'start': 0, 'end': 1}, str(tmp_path / 'assets'))
    store.finish(rid, {'shots': [{'large': 'x' * 10000}]}, {}, [])
    summary = store.list(pid)['items'][0]
    assert summary['result'] == {}
    assert store.get(rid)['result']['shots']
