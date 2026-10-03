from fastapi.testclient import TestClient

from app import api
from app.main import app
from db import ReferenceLibrary
from tests.test_audio import write_av_video


def test_save_unanalysed_rename_reopen_relink_and_identity(tmp_path):
    client = TestClient(app)
    source = write_av_video(tmp_path / "source.mp4", duration=1)
    assert client.post("/api/v1/video/import", json={"path": str(source)}).status_code == 200
    saved = client.post("/api/v1/project/save")
    assert saved.status_code == 200, saved.text
    pid = saved.json()["project_id"]
    renamed = client.put(f"/api/v1/projects/{pid}/name", json={"name": "我的参考"})
    assert renamed.status_code == 200
    assert client.post("/api/v1/project/save").json()["project_id"] == pid
    assert len(ReferenceLibrary().list_projects()) == 1
    asset = api._project_state.assets_dir
    api.reset_project_state()
    assert client.post(f"/api/v1/library/projects/{pid}/load").status_code == 200
    assert api._project_state.assets_dir == asset
    assert api._project_state.video.filename == "source.mp4"
    assert api._project_state.project_name == ReferenceLibrary().get_project(pid).name
    moved = tmp_path / "移动.mp4"
    moved.write_bytes(source.read_bytes())
    assert (
        client.post(f"/api/v1/projects/{pid}/relink", json={"path": str(moved)}).status_code == 200
    )
    wrong = tmp_path / "wrong.mp4"
    wrong.write_bytes(b"other")
    assert (
        client.post(f"/api/v1/projects/{pid}/relink", json={"path": str(wrong)}).status_code == 409
    )
    assert ReferenceLibrary().get_project(pid).video_path == str(moved)


def test_project_mutations_reject_busy_and_invalid_name(tmp_path):
    client = TestClient(app)
    source = write_av_video(tmp_path / "a.mp4", duration=1)
    client.post("/api/v1/video/import", json={"path": str(source)})
    pid = client.post("/api/v1/project/save").json()["project_id"]
    assert client.put(f"/api/v1/projects/{pid}/name", json={"name": " "}).status_code == 422
    with api._project_operation_lock:
        assert client.put(f"/api/v1/projects/{pid}/name", json={"name": "new"}).status_code == 409
        assert client.put("/api/v1/settings", json={}).status_code == 409


def test_basic_analysis_omits_models_and_marks_stages(tmp_path, monkeypatch):
    client = TestClient(app)
    source = write_av_video(tmp_path / "basic.mp4", duration=1)
    monkeypatch.setattr(
        api,
        "create_vision_provider",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not call")),
    )
    client.post("/api/v1/video/import", json={"path": str(source)})
    response = client.post("/api/v1/video/analyze", json={"mode": "basic"})
    assert response.status_code == 200, response.text
    progress = client.get("/api/v1/project/status").json()["progress"]
    assert progress["stages"]["vision_analysis"]["status"] == "skipped"
    assert api._project_state.shots[0].provider_versions["vision"]["provider"] == "disabled"
    pid = client.post("/api/v1/project/save").json()["project_id"]
    client.post(f"/api/v1/library/projects/{pid}/load")
    assert api._project_state.shots[0].provider_versions["ocr"]["provider"] == "disabled"
    report = client.post("/api/v1/export/markdown").json()["markdown"]
    assert "基础分析已省略" in report
    assert "文字 (Vision): 无" not in report


def test_save_missing_source_keeps_project_and_manual_tags(tmp_path):
    client = TestClient(app)
    source = write_av_video(tmp_path / "lost.mp4", duration=1)
    client.post("/api/v1/video/import", json={"path": str(source)})
    pid = client.post("/api/v1/project/save").json()["project_id"]
    original = ReferenceLibrary().get_project(pid).video_hash
    source.unlink()
    client.post(f"/api/v1/library/projects/{pid}/load")
    assert client.post("/api/v1/project/save").json()["project_id"] == pid
    assert len(ReferenceLibrary().list_projects()) == 1
    assert ReferenceLibrary().get_project(pid).video_hash == original
