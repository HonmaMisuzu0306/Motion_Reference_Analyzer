import pytest

from app.runtime_paths import RuntimePaths
from app.settings import SettingsStore
from schemas.settings import UserSettings


def test_settings_roundtrip_in_chinese_path(tmp_path):
    paths = RuntimePaths(data_root=tmp_path / "中文项目", legacy_root=tmp_path / "legacy")
    store = SettingsStore(paths)
    settings = UserSettings(qwen_model_id="qwen3-vl:4b", beat_sync_tolerance_ms=80)
    assert store.save(settings) == settings
    assert store.load() == settings
    original = paths.settings.read_bytes()
    with pytest.raises(ValueError):
        UserSettings(ollama_url="https://evil.example")
    assert paths.settings.read_bytes() == original


def test_corrupt_settings_does_not_silently_overwrite(tmp_path):
    paths = RuntimePaths(tmp_path, tmp_path / "legacy")
    paths.settings.write_text("{broken")
    with pytest.raises(ValueError, match="设置"):
        SettingsStore(paths).load()
    assert paths.settings.read_text() == "{broken"


def test_owned_release_ignores_development_model_bypass(monkeypatch):
    from app.config import get_config, reset_config

    monkeypatch.setenv("MRA_INSTANCE_ID", "owned-test")
    monkeypatch.setenv("REQUIRE_LOCAL_OCR_MODELS", "false")
    monkeypatch.setenv("VISION_PROVIDER", "mock")
    monkeypatch.setenv("QWEN_API_BASE", "https://remote.invalid")
    reset_config()
    config = get_config()
    assert config.require_local_ocr_models is True
    assert config.vision_provider == "qwen3-vl"
    assert config.qwen_api_base == "http://127.0.0.1:11434"
