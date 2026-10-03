"""Decode the first audio stream while preserving timestamps and gaps."""
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from video.timing import video_origin


@dataclass
class DecodedAudio:
    samples: np.ndarray
    sample_rate: int
    audio_start: float
    stream_index: int | None
    video_origin: float = 0


def decode_audio(path: Path, sample_rate: int = 22050, max_duration: float = 1800) -> DecodedAudio:
    if sample_rate < 8000 or sample_rate > 48000 or max_duration <= 0:
        raise ValueError('Invalid audio sample rate or duration limit')
    with av.open(str(path)) as container:
        audio = next(iter(container.streams.audio), None)
        if audio is None:
            return DecodedAudio(np.empty(0, np.float32), sample_rate, 0, None)
        video = next(iter(container.streams.video), None)
        # SceneDetect's zero is the first video frame, not the first audio frame.
        origin = video_origin(video) if video else 0
        resampler = av.AudioResampler(format='fltp', layout='mono', rate=sample_rate)
        chunks = []
        cursor, length = 0, 0
        first_time = None
        limit = round(max_duration * sample_rate)

        def append(frame):
            nonlocal cursor, length, first_time
            at = round((float(frame.pts * frame.time_base) - origin) * sample_rate) if frame.pts is not None else cursor
            values = frame.to_ndarray().reshape(-1).astype(np.float32, copy=False)
            if first_time is None:
                first_time = max(0, at / sample_rate)
            cursor = at + len(values)
            if cursor > limit:
                raise ValueError(f'音频时间轴超过 {max_duration:g}s 限制，请调整 AUDIO_MAX_DURATION')
            if at < 0:
                values, at = values[-at:], 0
            if len(values):
                chunks.append((at, values))
                length = max(length, at + len(values))

        for frame in container.decode(audio):
            for converted in resampler.resample(frame):
                append(converted)
        for converted in resampler.resample(None):
            append(converted)
        samples = np.zeros(length, np.float32)
        for at, values in chunks:
            samples[at:at + len(values)] = values
        return DecodedAudio(samples, sample_rate, first_time or 0, audio.index, origin)
