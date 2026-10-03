import json
import sqlite3

from app.runtime_paths import RuntimePaths
from projects.legacy_import import import_legacy_library
from selection.export import export_selection
from selection.store import SelectionStore
from tests.test_selection_store import database


def test_local_export_has_exact_identity_warnings_and_no_motion_for_frame(tmp_path):
    record = {'id': 'record', 'kind': 'frame', 'source_hash': 'sha', 'request': {},
              'status': 'done', 'result': {'kind': 'frame', 'time': {'pts': 640, 'actual_time': .04},
                                         'frame': {'text_regions': [], 'observations': {'composition': '居中'}}},
              'versions': {'pipeline': 'selection-pipeline-v1'}, 'warnings': ['单帧不能判断运动']}
    json_path = export_selection(record, 'json', tmp_path)
    assert json.loads(json_path.read_text(encoding='utf-8'))['result']['time']['pts'] == 640
    text = export_selection(record, 'markdown', tmp_path).read_text(encoding='utf-8')
    assert '0.040' in text and '640' in text and '单帧不能判断运动' in text and '居中' in text


def test_schema6_import_preserves_records_assets_and_missing_source_readonly(tmp_path):
    source = tmp_path / 'old'
    source.mkdir()
    store = SelectionStore(database(source / 'library.sqlite'))
    assets = source / 'selections/original'
    assets.mkdir(parents=True)
    (assets / 'frame.png').write_bytes(b'frame-evidence')
    rid = store.create(1, 'frame', 'sha', {'kind': 'frame'}, str(assets))
    store.finish(rid, {'kind': 'frame', 'frame': {'image': 'frame.png'}}, {}, [])
    before = store.database.read_bytes()
    target = RuntimePaths(tmp_path / 'new', source)
    assert import_legacy_library(store.database, source, target)['projects'] == 2
    imported = SelectionStore(target.database).get(rid)
    assert imported['result'] == {'kind': 'frame', 'frame': {'image': 'frame.png'}}
    assert (target.data_root / imported['assets_dir'].removeprefix('@data/') / 'frame.png').read_bytes() == b'frame-evidence'
    assert store.database.read_bytes() == before
    with sqlite3.connect(target.database) as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_import_missing_record_evidence_aborts_all_publication(tmp_path):
    import pytest

    source = tmp_path / 'old'
    source.mkdir()
    store = SelectionStore(database(source / 'library.sqlite'))
    assets = source / 'evidence'
    assets.mkdir()
    rid = store.create(1, 'frame', 'sha', {}, str(assets))
    store.finish(rid, {'kind': 'frame', 'frame': {'image': 'frame.png'}}, {}, [])
    target = RuntimePaths(tmp_path / 'new', source)
    with pytest.raises(ValueError, match='资产'):
        import_legacy_library(store.database, source, target)
    with sqlite3.connect(target.database) as conn:
        assert conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == 0


def test_imported_running_record_is_interrupted_without_worker(tmp_path):
    source = tmp_path / 'old'
    source.mkdir()
    store = SelectionStore(database(source / 'library.sqlite'))
    rid = store.create(1, 'clip', 'sha', {}, str(source / 'not-created'))
    store.update_progress(rid, 'vision', 0, 1, '运行中')
    target = RuntimePaths(tmp_path / 'new', source)
    import_legacy_library(store.database, source, target)
    record = SelectionStore(target.database).get(rid)
    assert record['status'] == 'interrupted' and record['error']
