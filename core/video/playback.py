"""Browser playback copy for media whose source PTS does not start at zero.

Compressed packets are remuxed without decoding/re-encoding; source files stay untouched.
"""
from pathlib import Path
from threading import Lock
from uuid import uuid4

import av

from video.playback_file import (
    PlaybackSourceChanged,
    check_key,
    file_key,
    open_media,
    verified_digest,
)
from video.timing import video_origin

_lock = Lock()


def playback_source(source: Path, cache_dir: Path, *, expected_hash: str | None = None) -> Path:
    path, file, _ = open_playback(source, cache_dir, expected_hash)
    file.close()
    return path


def open_playback(source: Path, cache_dir: Path, expected_hash: str | None):
    """Return the same open file that was verified; its caller owns the close."""
    file = open_media(source)
    try:
        key = file_key(file)
        if expected_hash and verified_digest(file, key) != expected_hash:
            raise PlaybackSourceChanged('源视频内容与分析时不同，请重新关联原视频')
        playable = _prepare(source, file, key, cache_dir, expected_hash)
        if playable != source:
            file.close()
            file = open_media(playable)
            key = file_key(file)
        else:
            check_key(file, key)
        file.seek(0)
        return playable, file, key
    except BaseException:
        file.close()
        raise


def _prepare(source, file, key, cache_dir, expected_hash):
    with av.open(file) as input_:
        origin = video_origin(input_.streams.video[0])
        if abs(origin) < 1e-6:
            return source
        if expected_hash:
            digest = expected_hash
        else:
            # PyAV is using this same descriptor. Preserve its read cursor.
            cursor = file.tell()
            digest = verified_digest(file, key)
            file.seek(cursor)
        target = cache_dir / f'{digest}-video-clock-v3.mp4'
        with _lock:
            if target.exists():
                check_key(file, key)
                return target
            cache_dir.mkdir(parents=True, exist_ok=True)
            staging = cache_dir / f'{digest}-{uuid4().hex}.tmp'
            try:
                with av.open(str(staging), 'w', format='mp4', options={'movflags': '+faststart', 'avoid_negative_ts': 'disabled'}) as output:
                    streams = [input_.streams.video[0]]
                    if input_.streams.audio:
                        streams.append(input_.streams.audio[0])
                    mapping = {s.index: output.add_stream_from_template(s) for s in streams}
                    # A container pixel-aspect override (e.g. MP4 pasp) may
                    # differ from the ratio in the compressed H.264 stream.
                    video = streams[0]
                    if video.sample_aspect_ratio and video.sample_aspect_ratio > 0:
                        mapping[video.index].codec_context.sample_aspect_ratio = video.sample_aspect_ratio
                    for packet in input_.demux(streams):
                        # PyAV's flush sentinel has no payload. With Matroska
                        # and B-frames a real leading keyframe can lack DTS.
                        if not packet.size:
                            continue
                        offset = round(origin / packet.time_base)
                        if packet.dts is not None:
                            packet.dts -= offset
                        if packet.pts is not None:
                            packet.pts -= offset
                        packet.stream = mapping[packet.stream.index]
                        output.mux(packet)
                check_key(file, key)
                staging.replace(target)
            finally:
                staging.unlink(missing_ok=True)
        return target
