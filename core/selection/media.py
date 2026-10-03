"""Local decoding; every observation is inside the requested half-open range."""
from importlib.metadata import version
from pathlib import Path

import av
import numpy as np

from schemas import TimeRange
from schemas.audio import AudioAnalysis, AudioPoint
from selection.frames import iter_range_frames
from selection.models import ResolvedFrame
from video.timing import video_origin


def detect_range_scenes(path: Path, start: float, end: float) -> list[TimeRange]:
    cuts, previous = [start], None
    for frame in iter_range_frames(path, start, end):
        h, w = frame.image.shape[:2]
        signature = frame.image[::max(1, h // 16), ::max(1, w // 16)].reshape(-1, 3).mean(axis=0)
        if previous is not None and np.linalg.norm(signature - previous) > 25:
            if frame.identity.actual_time > cuts[-1] + 1e-9:
                cuts.append(frame.identity.actual_time)
        previous = signature
    if previous is None:
        raise ValueError('选区中没有可解码帧')
    cuts.append(end)
    return [TimeRange(start=a, end=b, duration=b - a) for a, b in zip(cuts, cuts[1:])]


def sample_range_frames(path: Path, start: float, end: float, count: int) -> list[ResolvedFrame]:
    if count <= 0:
        return []
    targets = np.linspace(start, end, count + 2)[1:-1]
    best, distances = [None] * count, [float('inf')] * count
    for frame in iter_range_frames(path, start, end):
        for i, target in enumerate(targets):
            distance = abs(frame.identity.actual_time - target)
            if distance < distances[i]:
                best[i], distances[i] = frame, distance
    unique = {f.identity.pts: f for f in best if f is not None}
    return sorted(unique.values(), key=lambda f: f.identity.actual_time)


def analyze_range_audio(path: Path, start: float, end: float, *, sample_rate: int = 22050,
                        hop_length: int = 256) -> AudioAnalysis:
    result = AudioAnalysis(duration=end - start, sample_rate=sample_rate, hop_length=hop_length,
                           method='librosa-range-v1-source-clock')
    try:
        result.library_version = version('librosa')
        with av.open(str(path)) as container:
            if not container.streams.audio:
                result.status, result.message = 'no_audio', '视频无音轨'
                return result
            stream = container.streams.audio[0]
            origin = video_origin(container.streams.video[0]) if container.streams.video else 0
            result.video_origin, result.stream_index = origin, stream.index
            result.audio_start = float((stream.start_time or 0) * stream.time_base) - origin
            container.seek(int((max(0, start - 1) + origin) / stream.time_base), stream=stream, backward=True)
            resampler = av.AudioResampler(format='fltp', layout='mono', rate=sample_rate)
            y = np.zeros(round((end - start) * sample_rate), np.float32)

            def append(frame):
                if frame.pts is None:
                    raise ValueError('音频缺少时间戳')
                at = round((float(frame.pts * frame.time_base) - origin - start) * sample_rate)
                values = frame.to_ndarray().reshape(-1)
                left, right = max(0, at), min(len(y), at + len(values))
                if right > left:
                    y[left:right] = values[left - at:right - at]

            for frame in container.decode(stream):
                for converted in resampler.resample(frame):
                    append(converted)
                if frame.pts is not None and float(frame.pts * frame.time_base) - origin >= end:
                    break
            for converted in resampler.resample(None):
                append(converted)
        if len(y) < 2048:
            result.status, result.message = 'insufficient', '选区音频过短'
            return result
        step = max(1, int(np.ceil(len(y) / 800)))
        result.waveform = [AudioPoint(time=start + i / sample_rate,
                                     rms=float(np.sqrt(np.mean(y[i:i + step] ** 2))))
                           for i in range(0, len(y), step)]
        if np.max(np.abs(y)) < 1e-5:
            result.status, result.message = 'silent', '选区为静音'
            return result
        import librosa

        envelope = librosa.onset.onset_strength(y=y, sr=sample_rate, hop_length=hop_length)
        onsets = librosa.onset.onset_detect(onset_envelope=envelope, sr=sample_rate,
                                           hop_length=hop_length, units='time')
        result.onset_times = sorted(set(round(start + float(t), 6) for t in onsets if 0 <= t < end - start))
        if end - start < 8:
            result.status, result.message = 'insufficient', '少于8秒：仅提供波形与瞬态，不估计BPM和节拍同步'
            return result
        tempo, beats = librosa.beat.beat_track(onset_envelope=envelope, sr=sample_rate,
                                              hop_length=hop_length, units='time')
        result.beat_times = sorted(set(round(start + float(t), 6) for t in beats if 0 <= t < end - start))
        bpm = float(np.asarray(tempo).reshape(-1)[0])
        if len(result.beat_times) >= 3 and bpm > 0:
            result.tempo_bpm = round(bpm, 3)
            result.status, result.message = 'ok', '选区节拍为算法估计，瞬态不等同于节拍'
            intervals = np.diff(result.beat_times)
            result.beat_regularity = float(np.clip(1 - np.std(intervals) / np.mean(intervals), 0, 1))
        else:
            result.beat_times = []
            result.status, result.message = 'insufficient', '未检测到足够节拍，保留瞬态'
    except Exception as exc:
        result.status, result.message = 'error', f'选区音频分析失败：{exc}'
    return result
