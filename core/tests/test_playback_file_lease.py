"""Exercise actual requested byte ranges around source mutations and disconnects."""
import hashlib
import os
from shutil import copyfile

import pytest
from fastapi import HTTPException

from app import api
from video import playback_file


async def consume(response, *, byte_range=None, fail=False):
    messages = []

    async def send(message):
        if fail:
            raise OSError('client disconnected')
        messages.append(message)

    headers = [(b'range', byte_range)] if byte_range else []
    await response({'type': 'http', 'method': 'GET', 'headers': headers,
                    'asgi': {'spec_version': '2.4'}, 'extensions': {'http.response.pathsend': {}}},
                   None, send)
    assert not any(m['type'] == 'http.response.pathsend' for m in messages)
    return messages[0]['status'], b''.join(m.get('body', b'') for m in messages[1:])


@pytest.mark.asyncio
async def test_restoring_mtime_after_equal_size_edit_invalidates_cached_digest(tmp_path, sample_video, monkeypatch):
    source = tmp_path / 'source.mp4'
    copyfile(sample_video, source)
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    before = source.stat()
    calls = []
    hash_file = hashlib.file_digest

    def count(*args):
        calls.append(True)
        return hash_file(*args)

    monkeypatch.setattr(playback_file.hashlib, 'file_digest', count)
    def response():
        return api._verified_playback(source, digest)

    assert await consume(response(), byte_range=b'bytes=-8') == (206, data[-8:])
    assert await consume(response(), byte_range=b'bytes=8-20') == (206, data[8:21])
    assert len(calls) == 1
    with source.open('r+b') as file:
        file.seek(-1, os.SEEK_END)
        file.write(bytes([data[-1] ^ 1]))
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(HTTPException) as error:
        response()
    assert error.value.status_code == 409
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_source_replaced_between_validation_and_response(tmp_path, sample_video):
    source = tmp_path / 'source.mp4'
    other = tmp_path / 'replacement.mp4'
    copyfile(sample_video, source)
    data = source.read_bytes()
    other.write_bytes(b'x' * len(data))
    response = api._verified_playback(source, hashlib.sha256(data).hexdigest())
    if os.name == 'nt':
        with pytest.raises(PermissionError):
            other.replace(source)
        assert await consume(response) == (200, data)
        other.replace(source)
    else:
        other.replace(source)
        # POSIX may record the unlink as an inode change and stop the transfer.
        try:
            assert await consume(response) == (200, data)
        except playback_file.PlaybackSourceChanged:
            pass
    assert response.file.closed
    with pytest.raises(HTTPException) as error:
        api._verified_playback(source, hashlib.sha256(data).hexdigest())
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_disconnect_releases_source_before_next_attempt(tmp_path, sample_video):
    source = tmp_path / 'source.mp4'
    copyfile(sample_video, source)
    response = api._verified_playback(source, hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(OSError, match='client disconnected'):
        await consume(response, fail=True)
    assert response.file.closed
    source.unlink()
