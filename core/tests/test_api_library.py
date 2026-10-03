"""Tests for Library API endpoints."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["VISION_PROVIDER"] = "mock"
os.environ["OCR_PROVIDER"] = "mock"

from app.main import app  # noqa: E402
from db.connection import set_db_path


@pytest.fixture
def client(tmp_path):
    """Provide a TestClient with an isolated library database."""
    from app.api import reset_library

    set_db_path(tmp_path / "api_library.db")
    reset_library()
    return TestClient(app)


def test_library_projects_empty(client):
    """空库时应返回空项目列表。"""
    res = client.get("/api/v1/library/projects")
    assert res.status_code == 200
    assert res.json()["projects"] == []


def test_tags_empty(client):
    """空库时应返回空标签列表。"""
    res = client.get("/api/v1/tags")
    assert res.status_code == 200
    assert res.json()["tags"] == []


def test_create_tag(client):
    """可以创建新标签。"""
    res = client.post("/api/v1/tags", json={"name": "favorite", "color": "#ff0000"})
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "favorite"
    assert data["color"] == "#ff0000"
    assert data["id"] > 0


def test_search_empty(client):
    """空库搜索应返回空结果。"""
    res = client.post("/api/v1/search", json={"query": "test"})
    assert res.status_code == 200
    data = res.json()
    assert data["shots"] == []
    assert data["motion_types"] == []


def test_load_missing_project(client):
    """加载不存在的项目应返回 404。"""
    res = client.post("/api/v1/library/projects/999/load")
    assert res.status_code == 404
