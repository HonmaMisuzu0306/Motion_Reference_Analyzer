import hashlib

import pytest

from ocr.pending_cache import PendingOCRCache


def test_ocr_cache_writes_only_after_explicit_verified_publication(tmp_path):
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'original')
    cache = PendingOCRCache(tmp_path / 'cache', source, hashlib.sha256(source.read_bytes()).hexdigest())
    frames = [{'timestamp': .125, 'regions': []}]
    path = cache.set(source, 0, 1, {}, {}, frames)
    assert not path.exists()
    frames[0]['timestamp'] = .875
    cache.publish()
    assert cache.get(source, 0, 1, {}, {})[0]['timestamp'] == .125
    assert cache.pending == []


def test_changed_source_can_discard_buffer_without_polluting_any_cache_key(tmp_path):
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'original')
    cache = PendingOCRCache(tmp_path / 'cache', source, hashlib.sha256(source.read_bytes()).hexdigest())
    cache.set(source, 0, 1, {}, {}, [{'timestamp': .125, 'regions': []}])
    source.write_bytes(b'replaced')
    # The pipeline rejects the result and never calls publish.
    assert not list(cache.cache_dir.glob('*.json'))
    with pytest.raises(ValueError, match='跨源视频'):
        cache.get(tmp_path / 'other.mp4', 0, 1, {}, {})
