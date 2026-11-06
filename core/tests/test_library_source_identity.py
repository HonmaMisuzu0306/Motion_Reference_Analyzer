"""Persisted analysis keeps the source identity captured when it was verified."""
import pytest

from db import ReferenceLibrary
from db.paths import video_hash
from schemas import Project, Shot, VideoInfo
from tests.test_motion_curves import measured_shot


def verified_project(tmp_path, name='verified'):
    source = tmp_path / f'{name}.mp4'
    source.write_bytes(name.encode('utf-8'))
    return Project(
        project_name=name, video_path=str(source), source_hash=video_hash(source),
        video=VideoInfo(filename=source.name, duration=14, width=100, height=100, fps=24, codec='h264'),
        shots=[Shot.model_validate(measured_shot([0, .1, 0], [12.1, 12.5, 13.5]))],
    ), source


def snapshot(library):
    return tuple(library._conn.iterdump())


@pytest.mark.parametrize('operation', ['save_project', 'save_analysis'])
def test_new_project_rejects_replaced_source_before_any_database_writes(tmp_path, operation):
    library = ReferenceLibrary()
    unrelated, _ = verified_project(tmp_path, 'unrelated')
    library.save_analysis(unrelated)
    project, source = verified_project(tmp_path)
    before = snapshot(library)
    source.write_bytes(b'replacement')
    with pytest.raises(ValueError, match='源视频内容已改变'):
        getattr(library, operation)(project)
    assert snapshot(library) == before
    assert project.library_project_id is None


def test_missing_source_preserves_captured_identity_and_reuses_it_after_restore(tmp_path):
    library = ReferenceLibrary()
    project, source = verified_project(tmp_path)
    original = source.read_bytes()
    source.unlink()
    pid = library.save_analysis(project)
    assert library.get_project(pid).video_hash == project.source_hash
    assert library._conn.execute('SELECT content_hash FROM videos').fetchone()[0] == project.source_hash
    assert library.list_shots(pid)[0].measured_motion == project.shots[0].measured_motion.model_dump(mode='json')
    source.write_bytes(original)
    assert library.save_analysis(project) == pid
    assert len(library.list_projects()) == 1


@pytest.mark.parametrize('source_available', [False, True])
def test_known_project_rejects_another_captured_identity_even_without_source(tmp_path, source_available):
    library = ReferenceLibrary()
    original, _ = verified_project(tmp_path, 'original')
    pid = library.save_analysis(original)
    other, source = verified_project(tmp_path, 'other')
    other.library_project_id = pid
    if not source_available:
        source.unlink()
    before = snapshot(library)
    with pytest.raises(ValueError, match='分析来源与已保存项目不一致'):
        library.save_analysis(other)
    assert snapshot(library) == before


def test_known_matching_identity_and_tags_survive_missing_source(tmp_path):
    library = ReferenceLibrary()
    project, source = verified_project(tmp_path)
    pid = library.save_analysis(project)
    sid = library.list_shots(pid)[0].id
    library.set_manual_tags_by_id(sid, ['favorite'])
    project.library_project_id = pid
    source.unlink()
    assert library.save_analysis(project) == pid
    assert library.get_project(pid).video_hash == project.source_hash
    assert library.get_shot(sid).manual_tags == ['favorite']


@pytest.mark.parametrize('source_available', [False, True])
def test_historical_objects_without_captured_hash_keep_previous_identity_rules(tmp_path, source_available):
    library = ReferenceLibrary()
    project, source = verified_project(tmp_path)
    digest = project.source_hash
    project.source_hash = ''
    if not source_available:
        source.unlink()
    pid = library.save_analysis(project)
    identity = library.get_project(pid).video_hash
    assert identity == digest if source_available else identity.startswith('legacy:')


def test_invalid_captured_identity_is_not_stored_as_verified_hash(tmp_path):
    library = ReferenceLibrary()
    project, source = verified_project(tmp_path)
    source.unlink()
    project.source_hash = 'not-a-sha256'
    before = snapshot(library)
    with pytest.raises(ValueError, match='身份无效'):
        library.save_analysis(project)
    assert snapshot(library) == before
