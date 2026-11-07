"""CV cache entries belong to exact source content and analysis parameters."""
import hashlib
import json
import os

import pytest

from cv import cache as cache_module
from cv.cache import MotionCache
from schemas.measured_motion import MeasuredMotion


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.mp4'
    path.write_bytes(b'first content')
    return path


@pytest.fixture
def cache(tmp_path):
    return MotionCache(tmp_path / 'cv-cache')


def measurement(value=12):
    return MeasuredMotion(translation_x_px=value, confidence=.8, sample_count=8,
                          valid_pair_count=7, total_pair_count=7)


def test_same_name_size_and_mtime_replacement_cannot_reuse_motion(cache, source):
    cache.set(source, 0, 1, measurement())
    before = source.stat()
    source.write_bytes(b'other content')
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert cache.get(source, 0, 1) is None
    cache.set(source, 0, 1, measurement(-8))
    assert cache.get(source, 0, 1).translation_x_px == -8


def test_identical_content_can_reuse_motion_after_copy_or_rename(cache, source, tmp_path):
    cache.set(source, 0, 1, measurement())
    renamed = tmp_path / 'elsewhere' / 'different-name.mp4'
    renamed.parent.mkdir()
    renamed.write_bytes(source.read_bytes())
    assert cache.get(renamed, 0, 1).translation_x_px == 12


def test_exact_ranges_and_sampling_parameters_are_part_of_identity(cache, source):
    cache.set(source, .000001, 1.000001, measurement(), target_fps=8, max_long_edge=720)
    assert cache.get(source, .000002, 1.000001) is None
    assert cache.get(source, .000001, 1.000002) is None
    assert cache.get(source, .000001, 1.000001, target_fps=8.000001) is None
    assert cache.get(source, .000001, 1.000001, max_long_edge=721) is None
    assert cache.get(source, .000001, 1.000001, target_fps=8.0).translation_x_px == 12


def test_algorithm_version_invalidates_old_measurements(cache, source, monkeypatch):
    cache.set(source, 0, 1, measurement())
    monkeypatch.setattr(cache_module, 'CV_ALGORITHM_VERSION', 'next-version')
    assert cache.get(source, 0, 1) is None


def test_verified_source_hash_avoids_rehashing_each_shot(cache, source, monkeypatch):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    def unexpected_hash(path):
        raise AssertionError('caller already verified this analysis source')

    monkeypatch.setattr(cache, '_video_fingerprint', unexpected_hash)
    cache.set(source, 0, 1, measurement(), source_hash=digest)
    cache.set(source, 1, 2, measurement(-8), source_hash=digest)
    assert cache.get(source, 0, 1, source_hash=digest.upper()).translation_x_px == 12
    assert cache.get(source, 1, 2, source_hash=digest).translation_x_px == -8
    assert cache.get(source, 0, 1, source_hash='a' * 64) is None


@pytest.mark.parametrize('content', ['{broken', '{}', '[]', '{"status": "failed", "sample_count": 8, "pairs": []}',
    '{"status": "ok", "sample_count": 8, "pairs": [], "translation_x_px": NaN}',
    '{"status": "ok", "sample_count": 8, "pairs": [], "translation_x_px": 1e999}',
    '{"status": "ok", "sample_count": 8, "pairs": [{"dx_px": Infinity}]}'])
def test_bad_cached_data_is_a_miss_and_can_be_replaced(cache, source, content):
    path = cache.set(source, 0, 1, measurement())
    path.write_text(content, encoding='utf-8')
    assert cache.get(source, 0, 1) is None
    cache.set(source, 0, 1, measurement(-3))
    assert cache.get(source, 0, 1).translation_x_px == -3


def test_failed_analysis_is_not_persisted_or_allowed_to_replace_success(cache, source):
    failed = MeasuredMotion(status='failed', message='transient decode error')
    path = cache.set(source, 0, 1, failed)
    assert not path.exists()
    cache.set(source, 0, 1, measurement())
    before = path.read_bytes()
    cache.set(source, 0, 1, failed)
    assert path.read_bytes() == before
    assert cache.get(source, 0, 1).translation_x_px == 12


def test_insufficient_features_remains_a_cacheable_observation(cache, source):
    cache.set(source, 0, 1, MeasuredMotion(status='insufficient_features', sample_count=8))
    assert cache.get(source, 0, 1).status == 'insufficient_features'


def test_nonfinite_new_result_cannot_destroy_existing_entry(cache, source):
    path = cache.set(source, 0, 1, measurement())
    before = path.read_bytes()
    bad = measurement()
    bad.translation_x_px = float('nan')
    with pytest.raises(ValueError):
        cache.set(source, 0, 1, bad)
    assert path.read_bytes() == before
    assert list(cache.cache_dir.glob('*.tmp')) == []


def test_replace_failure_preserves_previous_entry_and_cleans_temp(cache, source, monkeypatch):
    path = cache.set(source, 0, 1, measurement())
    before = path.read_bytes()

    def fail_replace(source_path, target_path):
        assert target_path == path
        assert json.loads(source_path.read_text(encoding='utf-8'))['translation_x_px'] == -9
        raise OSError('disk unavailable')

    monkeypatch.setattr(cache_module.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='disk unavailable'):
        cache.set(source, 0, 1, measurement(-9))
    assert path.read_bytes() == before
    assert list(cache.cache_dir.glob('*.tmp')) == []


@pytest.mark.parametrize('kwargs', [
    {'source_hash': ''}, {'source_hash': 'not-a-sha256'}, {'source_hash': 'g' * 64},
    {'target_fps': 0}, {'target_fps': float('nan')}, {'max_long_edge': 0},
])
def test_invalid_identity_parameters_are_rejected(cache, source, kwargs):
    with pytest.raises(ValueError):
        cache.get(source, 0, 1, **kwargs)
