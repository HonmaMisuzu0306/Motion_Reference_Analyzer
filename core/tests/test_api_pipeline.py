"""Pipeline 级集成测试。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

# 强制使用 mock provider，避免真实模型/依赖阻塞测试
os.environ["VISION_PROVIDER"] = "mock"
os.environ["OCR_PROVIDER"] = "mock"

from app.main import app  # noqa: E402, I001


def test_import_and_analyze_sample_video(sample_video):
    """端到端：导入样本视频并完成分析，确认进度与 Shot 结构完整。"""
    client = TestClient(app)

    # 1. 导入视频
    res = client.post("/api/v1/video/import", json={"path": str(sample_video)})
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
    plan = shot['ae_recipe']['animation_plan']
    assert plan['source_start'] == shot['time']['start']
    assert plan['source_end'] == shot['time']['end']

    # 5. 导出 Markdown
    res = client.post("/api/v1/export/markdown")
    assert res.status_code == 200
    export = res.json()
    assert Path(export["path"]).exists()
    assert "Typography" in export["markdown"] or "文字" in export["markdown"]
    assert '关键帧时间' in export['markdown']
    assert '试作' in export['markdown']

    # 6. 导出 JSON
    res = client.post("/api/v1/export/json")
    assert res.status_code == 200
    export = res.json()
    assert Path(export["path"]).exists()
    assert "typography_tracks" in export["data"]["shots"][0]
    assert export['data']['shots'][0]['ae_recipe']['animation_plan'] == plan
