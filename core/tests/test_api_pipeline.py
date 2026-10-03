"""Pipeline 级集成测试。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

# 强制使用 mock provider，避免真实模型/依赖阻塞测试
os.environ["VISION_PROVIDER"] = "mock"
os.environ["OCR_PROVIDER"] = "mock"

from app.main import app  # noqa: E402, I001


SAMPLE_VIDEO = Path(__file__).parent.parent.parent / "samples" / "test_typography.mp4"


def test_import_and_analyze_sample_video():
    """端到端：导入样本视频并完成分析，确认进度与 Shot 结构完整。"""
    assert SAMPLE_VIDEO.exists(), f"样本视频不存在: {SAMPLE_VIDEO}"

    client = TestClient(app)

    # 1. 导入视频
    res = client.post("/api/v1/video/import", json={"path": str(SAMPLE_VIDEO)})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"

    # 2. 分析视频
    res = client.post("/api/v1/video/analyze")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "ok"
    assert len(data["shots"]) > 0

    # 3. 读取项目状态
    res = client.get("/api/v1/project/status")
    assert res.status_code == 200
    status = res.json()
    assert status["progress"]["status"] in {"done", "completed_with_warnings"}
    assert status["progress"]["overall_progress"] == 1.0
    assert "ocr_analysis" in status["progress"]["stages"]
    assert "typography_analysis" in status["progress"]["stages"]

    # 4. Shot 详情包含新字段
    res = client.get(f"/api/v1/shots/{data['shots'][0]['shot_id']}")
    assert res.status_code == 200
    shot = res.json()
    assert "text_regions" in shot
    assert "typography_tracks" in shot
    assert "ae_recipe" in shot

    # 5. 导出 Markdown
    res = client.post("/api/v1/export/markdown")
    assert res.status_code == 200
    export = res.json()
    assert Path(export["path"]).exists()
    assert "Typography" in export["markdown"] or "文字" in export["markdown"]

    # 6. 导出 JSON
    res = client.post("/api/v1/export/json")
    assert res.status_code == 200
    export = res.json()
    assert Path(export["path"]).exists()
    assert "typography_tracks" in export["data"]["shots"][0]
