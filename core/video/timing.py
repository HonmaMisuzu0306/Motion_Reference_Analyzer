"""Convert source PTS to the same first-video-frame clock used by shot times."""


def video_origin(stream) -> float:
    return float(stream.start_time * stream.time_base) if stream.start_time is not None else 0.0
