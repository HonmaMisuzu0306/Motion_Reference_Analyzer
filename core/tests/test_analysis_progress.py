"""Analysis Progress 测试。

验证进度状态来自真实 Pipeline，单调递增，错误与警告可被正确记录。
"""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import reset_project_state
from app.config import reset_config
from app.main import app
from app.progress import AnalysisProgressTracker
from vision.mock import MockVisionProvider


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("VISION_PROVIDER", "mock")
    monkeypatch.setenv("VISION_CACHE_DIR", str(tmp_path / "vision_cache"))
    monkeypatch.setenv("CV_CACHE_DIR", str(tmp_path / "cv_cache"))
    reset_config()
    reset_project_state()
    yield
    reset_project_state()
    reset_config()


@pytest.fixture(name="client")
def _client():
    return TestClient(app)


def _create_multi_shot_video(path: Path, duration: float = 3.0, fps: int = 24) -> Path:
    """创建包含明显切镜的合成视频，用于产生多个 Shot。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 320, 240
    total_frames = int(duration * fps)
    segment_frames = total_frames // 3
    colors = [
        (0, 0, 0),
        (255, 255, 255),
        (0, 128, 255),
    ]

    with av.open(str(path), "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"

        for i in range(total_frames):
            color = colors[(i // segment_frames) % len(colors)]
            frame = av.VideoFrame.from_ndarray(
                np.full((height, width, 3), color, dtype=np.uint8),
                format="bgr24",
            )
            for packet in stream.encode(frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

    return path


def _progress_from_response(data: dict) -> dict:
    return data.get("progress", {})


def test_progress_starts_at_zero(client: TestClient):
    response = client.get("/api/v1/project/status")
    assert response.status_code == 200
    progress = _progress_from_response(response.json())
    assert progress["overall_progress"] == 0.0
    assert progress["status"] == "idle"


def test_progress_scene_detect_completed(client: TestClient, tmp_path: Path):
    video = _create_multi_shot_video(tmp_path / "progress.mp4")
    client.post("/api/v1/video/import", json={"path": str(video)})
    response = client.post("/api/v1/video/analyze")
    assert response.status_code == 200

    status = client.get("/api/v1/project/status").json()
    progress = _progress_from_response(status)
    stages = progress["stages"]

    assert stages["scene_detect"]["status"] == "completed"
    assert stages["extract_frames"]["status"] == "completed"
    assert stages["vision_analysis"]["status"] == "completed"
    assert stages["cv_analysis"]["status"] == "completed"
    assert stages["recipe_generation"]["status"] == "completed"
    assert stages["saving"]["status"] == "completed"


def test_progress_overall_monotonic_and_reaches_one(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    video = _create_multi_shot_video(tmp_path / "progress.mp4")
    client.post("/api/v1/video/import", json={"path": str(video)})

    snapshots: list[float] = []
    original_recompute = AnalysisProgressTracker._recompute_overall

    def _recording_recompute(self: AnalysisProgressTracker) -> None:
        original_recompute(self)
        snapshots.append(self._progress.overall_progress)

    monkeypatch.setattr(
        AnalysisProgressTracker,
        "_recompute_overall",
        _recording_recompute,
    )

    response = client.post("/api/v1/video/analyze")
    assert response.status_code == 200

    # 进度必须单调不减
    assert snapshots == sorted(snapshots)
    assert snapshots[-1] == 1.0

    status = client.get("/api/v1/project/status").json()
    assert status["status"] == "done"
    assert status["progress"]["overall_progress"] == 1.0


def test_progress_error_state_without_import(client: TestClient):
    response = client.post("/api/v1/video/analyze")
    assert response.status_code == 400

    status = client.get("/api/v1/project/status").json()
    progress = _progress_from_response(status)
    assert progress["status"] == "error"
    assert progress["error"] is not None
    assert "未导入视频" in progress["error"]["message"]


def test_progress_completed_with_warnings(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    video = _create_multi_shot_video(tmp_path / "progress_warning.mp4")
    client.post("/api/v1/video/import", json={"path": str(video)})

    original_analyze = MockVisionProvider.analyze_shot

    def _failing_analyze(self, images, context):
        if context.shot_id == "shot_002":
            raise RuntimeError("模拟 Vision 失败")
        return original_analyze(self, images, context)

    monkeypatch.setattr(MockVisionProvider, "analyze_shot", _failing_analyze)

    response = client.post("/api/v1/video/analyze")
    assert response.status_code == 200

    status = client.get("/api/v1/project/status").json()
    progress = _progress_from_response(status)

    assert progress["status"] == "completed_with_warnings"
    assert progress["overall_progress"] == 1.0

    vision_stage = progress["stages"]["vision_analysis"]
    assert vision_stage["status"] == "completed"
    assert vision_stage["failed"] == 1
    assert vision_stage["completed"] >= 2

    shots = client.get("/api/v1/shots").json()["shots"]
    shot_002 = next((s for s in shots if s["shot_id"] == "shot_002"), None)
    assert shot_002 is not None
    assert "Vision 失败" in shot_002["analysis_error"]
