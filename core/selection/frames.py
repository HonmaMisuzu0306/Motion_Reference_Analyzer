"""Decode presentation PTS; a requested time belongs to the preceding frame."""
from math import isfinite
from pathlib import Path
from typing import Iterator, Literal

import av

from selection.models import FrameIdentity, ResolvedFrame
from selection.source import source_digest
from video.timing import video_origin


def _identity(stream, frame, source_hash, requested_time):
    tb = frame.time_base or stream.time_base
    return FrameIdentity(source_hash=source_hash, stream_index=stream.index, pts=frame.pts,
                         time_base_num=tb.numerator, time_base_den=tb.denominator,
                         video_origin=video_origin(stream), requested_time=requested_time,
                         actual_time=float(frame.pts * tb) - video_origin(stream))


def _seek(container, stream, relative_time):
    # Seeking before the target also retains its predecessor at a keyframe boundary.
    raw = max(video_origin(stream), relative_time + video_origin(stream) - 1)
    container.seek(int(raw / float(stream.time_base)), stream=stream, backward=True)


def locate_frame(path: Path, time: float, *, pts: int | None = None,
                 direction: Literal['current', 'previous', 'next'] = 'current') -> ResolvedFrame:
    if not isfinite(time) or time < 0 or direction not in ('current', 'previous', 'next'):
        raise ValueError('无效帧定位参数')
    digest = source_digest(path)
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('视频没有可解码画面')
        stream = container.streams.video[0]
        origin = video_origin(stream)
        if stream.duration is not None and time > float(stream.duration * stream.time_base) + 1e-6:
            raise ValueError('帧时间超出视频时长')
        target = time if pts is None else float(pts * stream.time_base) - origin
        _seek(container, stream, max(0, target))
        previous, chosen, last_decoded = None, None, None
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            actual = float(frame.pts * frame.time_base) - origin
            matches = frame.pts == pts if pts is not None else actual <= time + 1e-9
            if chosen is not None and (pts is not None or actual > time + 1e-9):
                if direction == 'next':
                    chosen = frame
                break
            if matches:
                previous, chosen = last_decoded, frame
            elif chosen is None and pts is None:
                chosen = frame
                break
            last_decoded = frame
        if chosen is None:
            raise ValueError('无法找到指定PTS或解码画面')
        if pts is not None and direction != 'next' and chosen.pts != pts:
            raise ValueError('无法找到指定PTS')
        if direction == 'previous' and previous is not None:
            chosen = previous
        return ResolvedFrame(_identity(stream, chosen, digest, time), chosen.to_ndarray(format='bgr24'))


def iter_range_frames(path: Path, start: float, end: float) -> Iterator[ResolvedFrame]:
    if not all(isfinite(t) for t in (start, end)) or not 0 <= start < end:
        raise ValueError('无效解码范围')
    digest = source_digest(path)
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('视频没有可解码画面')
        stream = container.streams.video[0]
        _seek(container, stream, start)
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            identity = _identity(stream, frame, digest, start)
            if identity.actual_time >= end - 1e-9:
                break
            if identity.actual_time >= start - 1e-9:
                yield ResolvedFrame(identity, frame.to_ndarray(format='bgr24'))
