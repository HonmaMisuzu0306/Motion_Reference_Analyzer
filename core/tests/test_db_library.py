"""Tests for SQLite Reference Library persistence layer."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Make sure each test gets an isolated database
os.environ.setdefault("MRA_TEST_DB", "1")

from db import ReferenceLibrary
from db.connection import set_db_path
from db.models import FilterSet
from schemas import Project, Shot, TimeRange, VideoInfo


@pytest.fixture
def temp_db(tmp_path: Path):
    """Provide an isolated SQLite database path for each test."""
    db_path = tmp_path / "test_library.db"
    set_db_path(db_path)
    yield db_path


@pytest.fixture
def library(temp_db: Path) -> ReferenceLibrary:
    """Create a fresh ReferenceLibrary instance."""
    return ReferenceLibrary()


def _make_project(name: str = "test_project") -> Project:
    return Project(
        project_name=name,
        video_path="/tmp/video.mp4",
        video=VideoInfo(
            filename="video.mp4",
            duration=30.0,
            width=1920,
            height=1080,
            fps=24.0,
            codec="h264",
        ),
        analysis_status="done",
    )


def _make_shot(shot_id: str, start: float, end: float) -> Shot:
    return Shot(
        shot_id=shot_id,
        time=TimeRange(start=start, end=end, duration=end - start),
        frames=["frame_01.jpg"],
        motion={"type": "static"},
        measured_motion={"status": "ok"},
    )


def test_save_and_load_project(library: ReferenceLibrary):
    """项目可以保存并重新加载。"""
    project = _make_project("project_1")
    pid = library.save_project(project)
    assert pid > 0

    loaded_project, loaded_shots = library.load_project(pid)
    assert loaded_project.name == "project_1"
    assert loaded_project.video_filename == "video.mp4"
    assert loaded_project.video_width == 1920
    assert loaded_shots == []


def test_save_and_list_shots(library: ReferenceLibrary):
    """Shots 可以保存并列出。"""
    project = _make_project("project_shots")
    pid = library.save_project(project)

    shot1 = _make_shot("shot_001", 0.0, 2.0)
    shot2 = _make_shot("shot_002", 2.0, 5.0)
    library.save_shots([shot1, shot2], pid)

    shots = library.list_shots(pid)
    assert len(shots) == 2
    assert shots[0].shot_id == "shot_001"
    assert shots[1].shot_id == "shot_002"


def test_shot_tags_crud(library: ReferenceLibrary):
    """Shot 标签可以添加、列出、移除。"""
    project = _make_project("project_tags")
    pid = library.save_project(project)

    shot = _make_shot("shot_tags_001", 0.0, 1.0)
    library.save_shot(shot, pid)

    assert library.tag_shot(pid, "shot_tags_001", "title")
    assert library.tag_shot(pid, "shot_tags_001", "favorite")

    shots = library.list_shots(pid)
    assert set(shots[0].tags) == {"title", "favorite"}

    all_tags = library.list_tags()
    assert len(all_tags) == 2

    assert library.untag_shot(pid, "shot_tags_001", "title")
    shots = library.list_shots(pid)
    assert shots[0].tags == ["favorite"]


def test_set_shot_tags_replace(library: ReferenceLibrary):
    """设置 Shot 标签会替换现有标签。"""
    project = _make_project("project_set_tags")
    pid = library.save_project(project)

    shot = _make_shot("shot_set_001", 0.0, 1.0)
    library.save_shot(shot, pid)

    library.tag_shot(pid, "shot_set_001", "old")
    library.set_shot_tags(pid, "shot_set_001", ["new1", "new2"])

    shots = library.list_shots(pid)
    assert set(shots[0].tags) == {"new1", "new2"}


def test_search_by_query(library: ReferenceLibrary):
    """全文搜索可以命中 shot_id 或 motion_type。"""
    project = _make_project("project_search")
    pid = library.save_project(project)

    shot = _make_shot("search_target", 0.0, 1.0)
    shot2 = _make_shot("other_shot", 1.0, 2.0)
    library.save_shots([shot, shot2], pid)

    results = library.search(FilterSet(query="search_target"))
    assert len(results) == 1
    assert results[0].shot_id == "search_target"


def test_search_by_motion_type(library: ReferenceLibrary):
    """按 motion_type 过滤。"""
    project = _make_project("project_filter_motion")
    pid = library.save_project(project)

    shot_static = _make_shot("static_shot", 0.0, 1.0)
    shot_zoom = _make_shot("zoom_shot", 1.0, 2.0)
    shot_zoom.motion = {"type": "zoom"}
    library.save_shots([shot_static, shot_zoom], pid)

    results = library.search(FilterSet(motion_types=["zoom"]))
    assert len(results) == 1
    assert results[0].shot_id == "zoom_shot"


def test_search_by_has_text(library: ReferenceLibrary):
    """按 has_text 过滤。"""
    project = _make_project("project_filter_text")
    pid = library.save_project(project)

    shot_no_text = _make_shot("no_text", 0.0, 1.0)
    shot_text = _make_shot("has_text", 1.0, 2.0)
    shot_text.text_regions = [{"text": "hello"}]
    library.save_shots([shot_no_text, shot_text], pid)

    results = library.search(FilterSet(has_text=True))
    assert len(results) == 1
    assert results[0].shot_id == "has_text"


def test_search_by_tags(library: ReferenceLibrary):
    """按标签过滤。"""
    project = _make_project("project_filter_tags")
    pid = library.save_project(project)

    shot_a = _make_shot("shot_a", 0.0, 1.0)
    shot_b = _make_shot("shot_b", 1.0, 2.0)
    library.save_shots([shot_a, shot_b], pid)

    library.set_shot_tags(pid, "shot_a", ["title"])
    library.set_shot_tags(pid, "shot_b", ["title", "favorite"])

    results = library.search(FilterSet(tags=["title", "favorite"]))
    assert len(results) == 1
    assert results[0].shot_id == "shot_b"


def test_delete_project_cascades(library: ReferenceLibrary):
    """删除项目会级联删除 shots。"""
    project = _make_project("project_delete")
    pid = library.save_project(project)

    shot = _make_shot("delete_me", 0.0, 1.0)
    library.save_shot(shot, pid)

    assert library.delete_project(pid)

    with pytest.raises(ValueError):
        library.load_project(pid)

    results = library.list_shots(pid)
    assert results == []


def test_project_list_order(library: ReferenceLibrary):
    """项目列表按更新时间倒序。"""
    p1 = _make_project("project_a")
    p2 = _make_project("project_b")
    library.save_project(p1)
    library.save_project(p2)

    projects = library.list_projects()
    assert projects[0].name == "project_b"
    assert projects[1].name == "project_a"
