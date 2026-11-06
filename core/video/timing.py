"""Convert source PTS to the same first-video-frame clock used by shot times."""


def video_origin(stream) -> float:
    return float(stream.start_time * stream.time_base) if stream.start_time is not None else 0.0


def relative_frame_time(stream, pts: int, time_base=None) -> float:
    """Subtract the source origin as rational PTS before one final float conversion.

    Converting absolute timestamps first loses low bits at nonzero origins;
    e.g. a frame at raw 10+10/24 seconds would incorrectly precede start=10/24.
    A missing stream start time preserves the existing absolute-zero origin.
    """
    if pts is None:
        raise ValueError('视频帧缺少实际时间戳')
    base = time_base if time_base is not None else stream.time_base
    origin = stream.start_time * stream.time_base if stream.start_time is not None else 0
    return float(pts * base - origin)


def picture_end(stream, sample) -> float:
    """Exclusive video-relative end of a decoded frame or a presentation packet."""
    base = sample.time_base or stream.time_base
    origin = (stream.start_time or 0) * stream.time_base
    duration = sample.duration
    span = duration * base if duration and duration > 0 else (
        1 / stream.average_rate if stream.average_rate else 0)
    return float(sample.pts * base - origin + span)
