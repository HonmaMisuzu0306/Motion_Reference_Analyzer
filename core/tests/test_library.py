"""Persistence/retrieval acceptance with real SQLite and portable fixture files."""
import shutil
import sqlite3

import pytest

from db import ReferenceLibrary
from db.connection import close_connection, set_db_path
from db.models import FilterSet
from db.schema import CREATE_SCHEMA_SQL, init_schema
from schemas import Project, Shot, TimeRange, VideoInfo


@pytest.fixture
def library(tmp_path):
    close_connection()
    set_db_path(tmp_path / 'library.db')
    lib = ReferenceLibrary()
    yield lib
    close_connection()


def project(path, name='sample'):
    return Project(project_name=name, video_path=str(path),
                   video=VideoInfo(filename=path.name, duration=5, width=1280,
                                   height=720, fps=24, codec='h264'))


def shot(name='shot_001', start=0, end=1):
    return Shot(shot_id=name, time=TimeRange(start=start, end=end, duration=end-start),
                motion={'type': 'camera_push', 'confidence': .85},
                observations={'scene_type': 'title_card', 'description': 'camera push'},
                typography={'has_text': True}, ae_recipe={'notes': 'Approximation'})


def test_content_identity_same_name_and_renamed_video(library, tmp_path):
    a = tmp_path / 'a.mp4'
    b = tmp_path / 'b.mp4'
    a.write_bytes(b'video a')
    b.write_bytes(b'video b')
    first = library.save_project(project(a))
    library.save_shot(shot(), first)
    second = library.save_project(project(b))
    assert first != second  # Same filename/stem must not overwrite different content.
    copied = tmp_path / 'renamed.mp4'
    shutil.copyfile(a, copied)
    assert library.save_project(project(copied, 'renamed')) == first
    assert library.save_shot(shot('different_label'), first) == library.list_shots(first)[0].id
    assert len(library.list_shots(first)) == 1


def test_auto_manual_tags_reanalysis_and_combined_filters(library, tmp_path):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'video')
    pid = library.save_project(project(path))
    library.save_shot(shot(), pid)
    library.tag_shot(pid, 'shot_001', 'favorite')
    library.save_shot(shot(), pid)
    saved = library.list_shots(pid)[0]
    assert {'camera_push', 'title_card', 'typography', 'favorite'} <= set(saved.tags)
    assert saved.motion_confidence == .85
    assert saved.analysis_version and saved.pipeline_version
    result = library.search(FilterSet(query='camera push', motion_types=['camera_push'],
        has_text=True, max_duration=2, min_confidence=.8, project_id=pid,
        tags=['favorite', 'typography']))
    assert [s.id for s in result] == [saved.id]
    assert library.search(FilterSet(min_confidence=.9)) == []
    assert library.search(FilterSet(project_id=pid+1)) == []
    changed = shot()
    changed.motion = {'type': 'static', 'confidence': .7}
    library.save_shot(changed, pid)
    assert 'camera_push' not in library.list_shots(pid)[0].tags
    assert 'favorite' in library.list_shots(pid)[0].tags


def test_keyword_literal_punctuation_and_tag_parameter_order(library, tmp_path):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'video')
    pid = library.save_project(project(path))
    library.save_shot(shot(), pid)
    library.tag_shot(pid, 'shot_001', 'favorite')
    assert len(library.search(FilterSet(query='camera', tags=['favorite']))) == 1
    assert library.search(FilterSet(query='" OR * :')) == []


def test_reopen_migration_and_deletion_keep_source(library, tmp_path):
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'video')
    pid = library.save_project(project(path))
    library.save_shot(shot(), pid)
    close_connection()
    reopened = ReferenceLibrary()
    assert reopened.load_project(pid)[1][0].ae_recipe['notes'] == 'Approximation'
    assert reopened.delete_project(pid)
    assert path.exists()
    legacy = sqlite3.connect(tmp_path / 'legacy.db')
    legacy.executescript(CREATE_SCHEMA_SQL)
    legacy.execute("INSERT INTO projects(name) VALUES ('legacy')")
    legacy.commit()
    init_schema(legacy)
    assert legacy.execute('PRAGMA user_version').fetchone()[0] >= 2
    assert legacy.execute('SELECT name FROM projects').fetchone()[0] == 'legacy'
    legacy.close()


@pytest.mark.parametrize('ranges', [[(0, .4), (.4, 1)], []])
def test_reanalysis_reload_keeps_only_current_shots_and_preserves_history(library, tmp_path, ranges):
    from fastapi.testclient import TestClient

    from app.main import app

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled source identity')
    old = project(source)
    old.assets_dir = str(tmp_path / 'run-old')
    old.shots = [shot()]
    pid = library.save_analysis(old)
    old_id = library.list_shots(pid)[0].id
    library.set_manual_tags_by_id(old_id, ['favorite'])
    current = old.model_copy(update={
        'library_project_id': pid,
        'assets_dir': str(tmp_path / 'run-current'),
        'shots': [shot(f'shot_{index:03d}', start, end)
                  for index, (start, end) in enumerate(ranges, 1)],
    })
    library.save_analysis(current)

    assert len(library.list_shots(pid)) == 1 + len(ranges)
    assert library.get_shot(old_id).manual_tags == ['favorite']
    assert [(s.start_time, s.end_time) for s in library.load_project(pid)[1]] == ranges
    client = TestClient(app)
    response = client.post(f'/api/v1/library/projects/{pid}/load')
    assert response.is_success, response.text
    exported = client.post('/api/v1/export/json').json()['data']['shots']
    assert [(s['time']['start'], s['time']['end']) for s in exported] == ranges
    listed = client.get('/api/v1/projects').json()['projects']
    assert next(p['shot_count'] for p in listed if p['id'] == pid) == len(ranges)


def test_failed_current_set_save_preserves_previous_membership(library, tmp_path, monkeypatch):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled source identity')
    old = project(source)
    old.assets_dir = str(tmp_path / 'run-old')
    old.shots = [shot()]
    pid = library.save_analysis(old)
    current = old.model_copy(update={
        'library_project_id': pid,
        'assets_dir': str(tmp_path / 'run-current'),
        'shots': [shot('shot_001', 0, .4), shot('shot_002', .4, 1)],
    })
    save_shot = library.save_shot

    def fail_second(value, project_id, commit=True):
        if value.time.start == .4:
            raise RuntimeError('injected second-shot save failure')
        return save_shot(value, project_id, commit=commit)

    monkeypatch.setattr(library, 'save_shot', fail_second)
    with pytest.raises(RuntimeError, match='second-shot save failure'):
        library.save_analysis(current)
    persisted, loaded = library.load_project(pid)
    assert persisted.assets_dir == old.assets_dir
    assert [(s.start_time, s.end_time) for s in loaded] == [(0, 1)]
    assert len(library.list_shots(pid)) == 1


def test_unmarked_legacy_shots_remain_readable_until_current_set_save(library, tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled legacy identity')
    legacy = project(source)
    pid = library.save_project(legacy)
    old_id = library.save_shot(shot(), pid)
    assert [s.id for s in library.load_project(pid)[1]] == [old_id]
    legacy.library_project_id = pid
    library.save_analysis(legacy)
    assert library.load_project(pid)[1] == []
    assert library.get_shot(old_id).id == old_id


def test_tag_save_from_another_run_keeps_current_shot_membership(library, tmp_path):
    from fastapi.testclient import TestClient

    from app import api
    from app.main import app

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled tag-save source')
    old = project(source)
    old.assets_dir = str(tmp_path / 'run-old')
    old.shots = [shot()]
    pid = library.save_analysis(old)
    api._project_state = old.model_copy(deep=True, update={
        'library_project_id': pid,
        'assets_dir': str(tmp_path / 'run-unsaved'),
    })
    client = TestClient(app)
    response = client.post('/api/v1/shots/shot_001/tags', json={'tags': ['favorite']})
    assert response.is_success, response.text
    loaded = library.load_project(pid)[1]
    assert [(s.start_time, s.end_time) for s in loaded] == [(0, 1)]
    assert loaded[0].manual_tags == ['favorite']
    listed = client.get('/api/v1/projects').json()['projects']
    assert next(p['shot_count'] for p in listed if p['id'] == pid) == 1


def test_import_relocates_assets_without_changing_current_membership(library, tmp_path, monkeypatch):
    from app.runtime_paths import RuntimePaths
    from db.connection import get_db_path
    from projects.legacy_import import import_legacy_library

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled import source')
    assets = tmp_path / 'run-source'
    assets.mkdir()
    old = project(source)
    old.assets_dir = str(assets)
    old.shots = [shot()]
    pid = library.save_analysis(old)
    old_id = library.list_shots(pid)[0].id
    library.set_manual_tags_by_id(old_id, ['favorite'])
    source_db = get_db_path()
    close_connection()
    target = RuntimePaths(tmp_path / 'target', tmp_path)
    import_legacy_library(source_db, tmp_path, target)
    monkeypatch.setenv('MRA_DATA_DIR', str(target.data_root))
    set_db_path(target.database)
    imported = ReferenceLibrary()
    saved, loaded = imported.load_project(pid)
    assert saved.assets_dir.startswith('@data/imported-')
    assert [(s.start_time, s.end_time) for s in loaded] == [(0, 1)]
    assert loaded[0].manual_tags == ['favorite']


@pytest.mark.parametrize('operation', ['set', 'add', 'remove'])
def test_tag_endpoints_target_reused_current_shot_instead_of_newer_archive(library, tmp_path, operation):
    from fastapi.testclient import TestClient

    from app import api
    from app.main import app

    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled split-merge-split identity')
    split = project(source)
    split.assets_dir = str(tmp_path / 'run-split')
    split.shots = [shot('shot_001', 0, .4), shot('shot_002', .4, 1)]
    pid = library.save_analysis(split)
    current_id = library.load_project(pid)[1][0].id
    merged = split.model_copy(update={
        'library_project_id': pid,
        'assets_dir': str(tmp_path / 'run-merged'),
        'shots': [shot('shot_001', 0, 1)],
    })
    library.save_analysis(merged)
    archived_id = library.load_project(pid)[1][0].id
    assert archived_id > current_id
    library.set_manual_tags_by_id(archived_id, ['archive-label'])
    split.library_project_id = pid
    split.assets_dir = str(tmp_path / 'run-split-again')
    library.save_analysis(split)
    library.set_manual_tags_by_id(current_id, ['remove-me'])
    api._project_state = split
    client = TestClient(app)

    if operation == 'set':
        response = client.post('/api/v1/shots/shot_001/tags', json={'tags': ['favorite']})
        expected = ['favorite']
    elif operation == 'add':
        response = client.post('/api/v1/shots/shot_001/tags/favorite')
        expected = ['favorite', 'remove-me']
    else:
        response = client.delete('/api/v1/shots/shot_001/tags/remove-me')
        expected = []
    assert response.is_success, response.text
    assert library.get_shot(current_id).manual_tags == expected
    assert library.get_shot(archived_id).manual_tags == ['archive-label']


def test_unmarked_legacy_tag_target_remains_latest_matching_id(library, tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'controlled legacy tag identity')
    pid = library.save_project(project(source))
    first_id = library.save_shot(shot('shot_001', 0, .4), pid)
    latest_id = library.save_shot(shot('shot_001', 0, 1), pid)
    assert latest_id > first_id
    assert library.tag_shot(pid, 'shot_001', 'favorite')
    assert library.get_shot(first_id).manual_tags == []
    assert library.get_shot(latest_id).manual_tags == ['favorite']
