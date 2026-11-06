"""Audio results must remain tied to the source bytes read for this request."""
import hashlib
import json
import os
from importlib.metadata import version

import numpy as np
import pytest

from audio import analyzer
from audio import cache as audio_cache
from audio.cache import AudioCache
from audio.decoder import DecodedAudio, decode_audio
from schemas.audio import AudioAnalysis
from tests.test_audio import write_wav


@pytest.mark.parametrize('use_cache', [True, False])
@pytest.mark.parametrize('force', [True, False])
def test_same_size_mtime_replacement_during_decode_is_not_published(tmp_path, monkeypatch, use_cache, force):
    path = write_wav(tmp_path / 'source.wav', np.full(22050, .2, np.float32))
    stamp = path.stat()
    cache = AudioCache(tmp_path / 'cache') if use_cache else None

    def replace_then_decode(path, sample_rate, max_duration):
        write_wav(path, np.zeros(22050, np.float32))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return decode_audio(path, sample_rate, max_duration)

    monkeypatch.setattr(analyzer, 'decode_audio', replace_then_decode)
    result = analyzer.analyze_audio(path, cache=cache, force=force)
    assert path.stat().st_size == stamp.st_size
    assert path.stat().st_mtime_ns == stamp.st_mtime_ns
    assert result.status == 'error'
    assert '源文件' in result.message and '改变' in result.message
    assert result.waveform == result.beat_times == result.onset_times == []
    assert not result.cache_hit
    if cache:
        assert list(cache.cache_dir.iterdir()) == []


def test_source_replacement_while_reading_cache_cannot_publish_old_result(tmp_path, monkeypatch):
    silence = np.zeros(22050, np.float32)
    path = write_wav(tmp_path / 'source.wav', silence)
    stamp = path.stat()
    cache = AudioCache(tmp_path / 'cache')
    assert analyzer.analyze_audio(path, cache=cache).status == 'silent'
    get = cache.get

    def get_then_replace(key):
        result = get(key)
        assert result is not None
        write_wav(path, np.full(22050, .2, np.float32))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return result

    monkeypatch.setattr(cache, 'get', get_then_replace)
    result = analyzer.analyze_audio(path, cache=cache)
    assert result.status == 'error'
    assert '源文件' in result.message and '改变' in result.message
    assert result.waveform == [] and not result.cache_hit
    # The existing entry still correctly belongs to the old content.
    monkeypatch.setattr(cache, 'get', get)
    write_wav(path, silence)
    restored = analyzer.analyze_audio(path, cache=cache)
    assert restored.status == 'silent' and restored.cache_hit


@pytest.mark.parametrize('use_cache', [True, False])
def test_source_removed_after_decode_is_not_published(tmp_path, monkeypatch, use_cache):
    path = write_wav(tmp_path / 'source.wav', np.zeros(22050, np.float32))
    cache = AudioCache(tmp_path / 'cache') if use_cache else None

    def decode_then_remove(path, sample_rate, max_duration):
        result = decode_audio(path, sample_rate, max_duration)
        path.unlink()
        return result

    monkeypatch.setattr(analyzer, 'decode_audio', decode_then_remove)
    result = analyzer.analyze_audio(path, cache=cache)
    assert result.status == 'error'
    assert '源文件' in result.message
    assert result.waveform == [] and not result.cache_hit
    if cache:
        assert list(cache.cache_dir.iterdir()) == []


@pytest.mark.parametrize('use_cache', [True, False])
def test_unreadable_source_is_rejected_before_decode(tmp_path, monkeypatch, use_cache):
    cache = AudioCache(tmp_path / 'cache') if use_cache else None
    calls = []

    def fake_decode(*args):
        calls.append(args)
        return DecodedAudio(np.zeros(22050, np.float32), 22050, 0, 0)

    monkeypatch.setattr(analyzer, 'decode_audio', fake_decode)
    result = analyzer.analyze_audio(tmp_path / 'missing.wav', cache=cache)
    assert result.status == 'error'
    assert calls == []
    assert result.waveform == []
    if cache:
        assert list(cache.cache_dir.iterdir()) == []


def test_missing_source_after_cache_lookup_does_not_publish_a_hit(tmp_path, monkeypatch):
    path = write_wav(tmp_path / 'source.wav', np.zeros(22050, np.float32))
    cache = AudioCache(tmp_path / 'cache')
    assert analyzer.analyze_audio(path, cache=cache).status == 'silent'
    get = cache.get

    def get_then_remove(key):
        result = get(key)
        path.unlink()
        return result

    monkeypatch.setattr(cache, 'get', get_then_remove)
    result = analyzer.analyze_audio(path, cache=cache)
    assert result.status == 'error' and not result.cache_hit
    assert '无法读取音频源文件' in result.message
    assert len(list(cache.cache_dir.glob('*.json'))) == 1


def test_each_request_reads_content_twice_and_cache_hits_skip_decode(tmp_path, monkeypatch):
    path = write_wav(tmp_path / 'source.wav', np.zeros(22050, np.float32))
    cache = AudioCache(tmp_path / 'cache')
    original_digest = audio_cache.source_digest
    reads, decodes = [], []

    def count_digest(path):
        reads.append(path)
        return original_digest(path)

    def count_decode(*args):
        decodes.append(args)
        return decode_audio(*args)

    monkeypatch.setattr(audio_cache, 'source_digest', count_digest)
    monkeypatch.setattr(analyzer, 'source_digest', count_digest)
    monkeypatch.setattr(analyzer, 'decode_audio', count_decode)
    assert not analyzer.analyze_audio(path, cache=cache).cache_hit
    assert len(reads) == 2 and len(decodes) == 1
    assert analyzer.analyze_audio(path, cache=cache).cache_hit
    assert len(reads) == 4 and len(decodes) == 1
    assert not analyzer.analyze_audio(path, cache=cache, force=True).cache_hit
    assert len(reads) == 6 and len(decodes) == 2


def test_legacy_unverified_cache_namespace_is_not_reused(tmp_path):
    path = write_wav(tmp_path / 'source.wav', np.zeros(22050, np.float32))
    cache = AudioCache(tmp_path / 'cache')
    parameters = {'method': analyzer.METHOD, 'library': version('librosa'),
                  'sample_rate': 22050, 'hop_length': 256, 'max_duration': 1800}
    legacy = hashlib.sha256(path.read_bytes())
    legacy.update(json.dumps(parameters, sort_keys=True).encode())
    cache.set(legacy.hexdigest(), AudioAnalysis(status='no_audio'))
    result = analyzer.analyze_audio(path, cache=cache)
    assert result.status == 'silent' and not result.cache_hit
    assert cache.key(path, **parameters) != legacy.hexdigest()
    assert analyzer.analyze_audio(path, cache=cache).cache_hit
