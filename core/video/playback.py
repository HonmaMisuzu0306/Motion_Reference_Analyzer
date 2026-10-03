"""Browser playback copy for media whose source PTS does not start at zero.

Compressed packets are remuxed without decoding/re-encoding; source files stay untouched.
"""
import hashlib
from functools import lru_cache
from pathlib import Path
from threading import Lock
from uuid import uuid4

import av

from video.timing import video_origin

_lock = Lock()


@lru_cache(maxsize=16)
def _content_hash(path: str, size: int, mtime: int, ctime: int) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def playback_source(source: Path, cache_dir: Path) -> Path:
    with av.open(str(source)) as input_:
        origin = video_origin(input_.streams.video[0])
        if abs(origin) < 1e-6:
            return source
        stat = source.stat()
        digest = _content_hash(str(source.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        target = cache_dir / f'{digest}-video-clock-v1.mp4'
        with _lock:
            if target.exists():
                return target
            cache_dir.mkdir(parents=True, exist_ok=True)
            staging = cache_dir / f'{digest}-{uuid4().hex}.tmp'
            try:
                with av.open(str(staging), 'w', format='mp4', options={'movflags': '+faststart', 'avoid_negative_ts': 'disabled'}) as output:
                    streams = [input_.streams.video[0]]
                    if input_.streams.audio:
                        streams.append(input_.streams.audio[0])
                    mapping = {s.index: output.add_stream_from_template(s) for s in streams}
                    for packet in input_.demux(streams):
                        if packet.dts is None:
                            continue
                        offset = round(origin / packet.time_base)
                        packet.dts -= offset
                        if packet.pts is not None:
                            packet.pts -= offset
                        packet.stream = mapping[packet.stream.index]
                        output.mux(packet)
                staging.replace(target)
            finally:
                staging.unlink(missing_ok=True)
        return target
