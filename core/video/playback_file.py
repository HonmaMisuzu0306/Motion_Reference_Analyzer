"""Pin the source used for playback and verify repeat requests without rescanning a movie."""
import hashlib
import os
from collections import OrderedDict
from pathlib import Path
from threading import RLock

_hashes = OrderedDict()
_cache_lock = RLock()


class PlaybackSourceChanged(ValueError):
    pass


if os.name == 'nt':
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _win = ctypes.WinDLL('kernel32', use_last_error=True)
    _create = _win.CreateFileW
    _create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _create.restype = wintypes.HANDLE
    _info = _win.GetFileInformationByHandleEx
    _info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _info.restype = wintypes.BOOL
    _close = _win.CloseHandle
    _close.argtypes = [wintypes.HANDLE]
    _close.restype = wintypes.BOOL

    class _BasicInfo(ctypes.Structure):
        _fields_ = [('creation', ctypes.c_int64), ('access', ctypes.c_int64),
                    ('write', ctypes.c_int64), ('change', ctypes.c_int64),
                    ('attributes', wintypes.DWORD)]


def open_media(path: Path):
    if os.name != 'nt':
        return path.open('rb')
    # An existing writer causes a sharing violation; new writers and replacements
    # wait until this one response has finished. Other readers can still seek.
    handle = _create(str(path.resolve()), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        err = ctypes.get_last_error()
        if err in (32, 33):
            raise PlaybackSourceChanged('源视频正在写入，请稍后重新打开')
        raise ctypes.WinError(err)
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _close(handle)
        raise
    return os.fdopen(descriptor, 'rb')


def file_key(file):
    stat = os.fstat(file.fileno())
    change = stat.st_ctime_ns
    if os.name == 'nt':
        # Python's Windows st_ctime is creation time, even after an in-place write.
        info = _BasicInfo()
        handle = msvcrt.get_osfhandle(file.fileno())
        change = info.change if _info(handle, 0, ctypes.byref(info), ctypes.sizeof(info)) else 0
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, change


def check_key(file, key):
    if file_key(file) != key:
        raise PlaybackSourceChanged('播放期间源视频发生变化，请重新打开原视频')


def verified_digest(file, key):
    cacheable = bool(key[1] and key[-1])
    with _cache_lock:
        if cacheable and key in _hashes:
            _hashes.move_to_end(key)
            return _hashes[key]
    file.seek(0)
    digest = hashlib.file_digest(file, 'sha256').hexdigest()
    file.seek(0)
    check_key(file, key)
    if cacheable:
        with _cache_lock:
            _hashes[key] = digest
            if len(_hashes) > 128:
                _hashes.popitem(last=False)
    return digest
