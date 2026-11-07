"""Decode presentation PTS; a requested time belongs to the preceding frame."""
from math import isfinite
from pathlib import Path
from typing import Iterator, Literal

import av

from selection.models import FrameIdentity, ResolvedFrame
from selection.source import source_digest
from video.orientation import display_bgr
from video.timing import relative_frame_time, video_origin


def _identity(stream, frame, source_hash, requested_time):
    tb = frame.time_base or stream.time_base
    return FrameIdentity(source_hash=source_hash, stream_index=stream.index, pts=frame.pts,
                         time_base_num=tb.numerator, time_base_den=tb.denominator,
                         video_origin=video_origin(stream), requested_time=requested_time,
                         actual_time=relative_frame_time(stream, frame.pts, tb))


def _seek(container, stream, relative_time):
    # Seeking before the target also retains its predecessor at a keyframe boundary.
    raw = max(video_origin(stream), relative_time + video_origin(stream) - 1)
    container.seek(int(raw / stream.time_base), stream=stream, backward=True)


def locate_frame(path: Path, time: float, *, pts: int | None = None,
                 direction: Literal['current', 'previous', 'next', 'presented'] = 'current') -> ResolvedFrame:
    if not isfinite(time) or time < 0 or direction not in ('current', 'previous', 'next', 'presented'):
        raise ValueError('无效帧定位参数')
    if direction == 'presented' and pts is not None:
        raise ValueError('呈现帧时钟与精确 PTS 不能同时指定')
    digest = source_digest(path)
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('视频没有可解码画面')
        stream = container.streams.video[0]
        if stream.duration is not None and time > float(stream.duration * stream.time_base) + 1e-6:
            raise ValueError('帧时间超出视频时长')
        target = time if pts is None else relative_frame_time(stream, pts)
        _seek(container, stream, max(0, target))
        previous, chosen, last_decoded = None, None, None
        for frame in container.decode(stream):
            if frame.pts is None:
                raise ValueError('视频帧缺少实际时间戳')
            actual = relative_frame_time(stream, frame.pts, frame.time_base)
            # Compositor metadata reports microseconds; compare like clocks only for a
            # presented-frame capture. Manual times keep their strict half-open semantics.
            if pts is not None:
                matches = frame.pts == pts
            elif direction == 'presented':
                matches = round(actual, 6) <= round(time, 6)
            else:
                matches = actual <= time
            if chosen is not None and (pts is not None or not matches):
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
        return ResolvedFrame(_identity(stream, chosen, digest, time), display_bgr(chosen, stream))


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
                raise ValueError('视频帧缺少实际时间戳')
            identity = _identity(stream, frame, digest, start)
            if identity.actual_time >= end:
                break
            if identity.actual_time >= start:
                # FFmpeg 2 means unspecified. Explicit HDR/log transfer or wide-gamut
                # primaries cannot be compared safely after conversion to 8-bit BGR.
                supports_sdr = (frame.color_trc in (1, 2, 6, 13) and frame.color_primaries in (1, 2, 5, 6)
                                and stream.codec_context.color_trc in (1, 2, 6, 13)
                                and stream.codec_context.color_primaries in (1, 2, 5, 6))
                yield ResolvedFrame(identity, display_bgr(frame, stream), supports_sdr)
