from pathlib import Path

import httpx

from models.catalog import recommendations
from models.ollama import OllamaInspector


def test_official_catalog_has_candidates_and_no_cloud():
    rows = recommendations()
    assert [r["id"] for r in rows[:3]] == ["qwen3-vl:2b", "qwen3-vl:4b", "qwen3-vl:8b"]
    assert all(r["official_url"].startswith("https://") for r in rows)


def test_inspection_is_read_only_and_rejects_non_vision():
    seen = []

    def transport(req):
        seen.append(req.url.path)
        if req.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "text-only", "size": 20},
                        {"name": "qwen3-vl:4b", "size": 30},
                    ]
                },
            )
        return httpx.Response(
            200, json={"capabilities": ["vision"] if b"qwen3" in req.content else ["completion"]}
        )

    result = OllamaInspector(
        "http://localhost:11434", transport=httpx.MockTransport(transport)
    ).inspect()
    assert result["connected"]
    assert not result["models"][0]["vision"]
    assert result["models"][1]["vision"]
    assert set(seen) == {"/api/tags", "/api/show"}


def write_local_model(directory: Path, name: str):
    directory.mkdir(parents=True)
    (directory / 'inference.pdiparams').write_bytes(b'local-test-weights')
    (directory / 'inference.json').write_text('{}')
    (directory / 'inference.yml').write_text(f'Global:\n  model_name: {name}\n')


def test_existing_ocr_models_are_found_without_config_or_download(tmp_path):
    from models.ocr_paths import discover_ocr_models

    write_local_model(tmp_path / 'PP-OCRv5_server_det', 'PP-OCRv5_server_det')
    write_local_model(tmp_path / 'PP-OCRv5_server_rec', 'PP-OCRv5_server_rec')
    write_local_model(tmp_path / 'en_PP-OCRv5_mobile_rec', 'en_PP-OCRv5_mobile_rec')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    found = discover_ocr_models(tmp_path)
    assert len(found) == 2
    assert found[0]['languages'] == ['ch', 'japan', 'en']
    assert found[1]['languages'] == ['en']
    assert found[0]['recognition_dir'] == str(tmp_path / 'PP-OCRv5_server_rec')
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_incomplete_or_wrong_identity_cache_is_not_offered_as_ready(tmp_path):
    from models.ocr_paths import discover_ocr_models

    write_local_model(tmp_path / 'PP-OCRv5_server_det', 'PP-OCRv5_server_det')
    write_local_model(tmp_path / 'PP-OCRv5_server_rec', 'PP-OCRv6_server_rec')
    write_local_model(tmp_path / 'en_PP-OCRv5_mobile_rec', 'en_PP-OCRv5_mobile_rec')
    (tmp_path / 'en_PP-OCRv5_mobile_rec' / 'inference.pdiparams').unlink()
    assert discover_ocr_models(tmp_path) == []


def test_discovery_uses_complete_mobile_detector_when_server_export_is_incomplete(tmp_path):
    from models.ocr_paths import discover_ocr_models

    write_local_model(tmp_path / 'PP-OCRv5_server_det', 'PP-OCRv5_server_det')
    (tmp_path / 'PP-OCRv5_server_det' / 'inference.pdiparams').unlink()
    write_local_model(tmp_path / 'PP-OCRv5_mobile_det', 'PP-OCRv5_mobile_det')
    write_local_model(tmp_path / 'PP-OCRv5_server_rec', 'PP-OCRv5_server_rec')
    found = discover_ocr_models(tmp_path)
    assert len(found) == 1
    assert found[0]['detection_dir'] == str(tmp_path / 'PP-OCRv5_mobile_det')


def test_model_status_distinguishes_existing_files_from_saved_configuration(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    root = tmp_path / '.paddlex' / 'official_models'
    write_local_model(root / 'PP-OCRv5_server_det', 'PP-OCRv5_server_det')
    write_local_model(root / 'PP-OCRv5_server_rec', 'PP-OCRv5_server_rec')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(OllamaInspector, 'inspect', lambda self: {'connected': False, 'message': 'offline', 'models': []})
    client = TestClient(app)
    ocr = client.get('/api/v1/models/status').json()['ocr']
    assert ocr['configured'] is False
    assert len(ocr['discovered_models']) == 1
    settings = client.get('/api/v1/settings').json()
    assert settings['ocr_models'] == []
    candidate = ocr['discovered_models'][0]
    settings['ocr_models'] = [{'language': 'japan', 'detection_dir': candidate['detection_dir'], 'recognition_dir': candidate['recognition_dir']}]
    assert client.put('/api/v1/settings', json=settings).status_code == 200
    selected = client.get('/api/v1/models/status').json()['ocr']
    assert selected['configured'] is True and selected['available'] is True
    assert client.get('/api/v1/settings').json()['qwen_model_id'] == 'qwen3-vl:4b'


def test_missing_ocr_fails_before_ollama_and_reports_actual_reason(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import reset_config
    from app.main import app
    from tests.test_audio import write_av_video

    monkeypatch.setenv('MRA_INSTANCE_ID', 'owned-preflight-test')
    reset_config()
    monkeypatch.setattr(OllamaInspector, 'inspect', lambda self: (_ for _ in ()).throw(AssertionError('must validate missing OCR first')))
    client = TestClient(app)
    video = write_av_video(tmp_path / 'source.mp4', duration=1)
    assert client.post('/api/v1/video/import', json={'path': str(video)}).status_code == 200
    response = client.post('/api/v1/video/analyze', json={'mode': 'full'})
    assert response.status_code == 409
    reason = response.json()['detail']
    assert 'OCR' in reason and '下载' not in reason
    status = client.get('/api/v1/project/status').json()
    assert status['progress']['error']['message'] == reason
