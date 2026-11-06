"""Every test gets a temporary Library; regression runs never write the user's archive."""
import pytest

from app import api
from app.config import reset_config
from db.connection import get_db_path, set_db_path


@pytest.fixture(scope='session')
def sample_video(tmp_path_factory):
    """Generate real media for API tests without relying on an untracked sample file."""
    from tests.test_metadata import _create_test_video

    return _create_test_video(tmp_path_factory.mktemp('media') / 'sample.mp4', duration=5)


@pytest.fixture
def paddle_metadata(monkeypatch):
    """Stub native package metadata only in tests that already substitute the OCR engine."""
    import importlib.metadata

    real_version = importlib.metadata.version

    def version(name):
        return '3.3.1' if name == 'paddlepaddle' else real_version(name)

    monkeypatch.setattr(importlib.metadata, 'version', version)


@pytest.fixture(autouse=True)
def isolated_library(tmp_path, monkeypatch):
    previous = get_db_path()
    api.reset_library()
    api.reset_project_state()
    reset_config()
    monkeypatch.setenv('MRA_DATA_DIR',str(tmp_path/'output'))
    for key in ['VISION_CACHE_DIR', 'OCR_CACHE_DIR', 'CV_CACHE_DIR', 'TYPOGRAPHY_CACHE_DIR', 'AUDIO_CACHE_DIR']:
        monkeypatch.setenv(key, str(tmp_path / key.lower()))
    monkeypatch.setattr(api, 'OUTPUT_DIR', tmp_path / 'output')
    set_db_path(tmp_path / 'isolated_library.db')
    yield
    api.reset_library()
    api.reset_project_state()
    reset_config()
    set_db_path(previous)
