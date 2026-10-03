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
