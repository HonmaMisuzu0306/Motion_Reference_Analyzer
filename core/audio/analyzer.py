"""Whole-video beat and onset detection using real decoded audio."""
import logging
from importlib.metadata import version
from pathlib import Path

import numpy as np

from audio.cache import AudioCache
from audio.decoder import decode_audio
from schemas.audio import AudioAnalysis, AudioPoint

METHOD = 'librosa-beat-onset-v2-video-clock'


def analyze_audio(path: Path, *, sample_rate: int = 22050, hop_length: int = 256,
                  max_duration: float = 1800, cache: AudioCache | None = None,
                  force: bool = False) -> AudioAnalysis:
    result = AudioAnalysis(sample_rate=sample_rate, hop_length=hop_length)
    try:
        result.library_version = version('librosa')
        key = None
        if cache:
            key = cache.key(Path(path), method=METHOD, library=result.library_version,
                            sample_rate=sample_rate, hop_length=hop_length, max_duration=max_duration)
            if not force and (cached := cache.get(key)):
                return cached
        decoded = decode_audio(Path(path), sample_rate, max_duration)
        result.audio_start = decoded.audio_start
        result.video_origin = decoded.video_origin
        result.stream_index = decoded.stream_index
        result.duration = len(decoded.samples) / sample_rate
        if decoded.stream_index is None:
            result.status, result.message = 'no_audio', '视频无音轨'
        elif len(decoded.samples) < 2048:
            result.status, result.message = 'insufficient', '音轨过短，无法可靠估计节奏'
        else:
            y = decoded.samples
            # Fixed-size presentation envelope; event timestamps keep full resolution.
            step = max(1, int(np.ceil(len(y) / 800)))
            result.waveform = [AudioPoint(time=i / sample_rate,
                                         rms=float(np.sqrt(np.mean(y[i:i + step] ** 2))))
                               for i in range(0, len(y), step)]
            if float(np.max(np.abs(y))) < 1e-5:
                result.status, result.message = 'silent', '音轨为静音，未检测到节拍'
            else:
                import librosa

                envelope = librosa.onset.onset_strength(y=y, sr=sample_rate, hop_length=hop_length)
                onsets = librosa.onset.onset_detect(onset_envelope=envelope, sr=sample_rate,
                                                   hop_length=hop_length, units='time')
                tempo, beats = librosa.beat.beat_track(onset_envelope=envelope, sr=sample_rate,
                                                      hop_length=hop_length, units='time')
                result.onset_times = sorted(set(round(float(t), 6) for t in onsets if 0 <= t < result.duration))
                result.beat_times = sorted(set(round(float(t), 6) for t in beats if 0 <= t < result.duration))
                bpm = float(np.asarray(tempo).reshape(-1)[0])
                if len(result.beat_times) >= 3 and bpm > 0:
                    result.tempo_bpm = round(bpm, 3)
                    intervals = np.diff(result.beat_times)
                    result.beat_regularity = round(float(np.clip(1 - np.std(intervals) / np.mean(intervals), 0, 1)), 3)
                    result.status, result.message = 'ok', '节拍为算法估计；onset为瞬态事件，均不代表作者意图'
                else:
                    result.beat_times = []
                    result.status, result.message = 'insufficient', '未检测到足够的节拍；保留瞬态事件供参考'
        if cache and key:
            try:
                cache.set(key, result)
            except OSError as exc:
                logging.getLogger(__name__).warning('Audio cache write failed: %s', exc)
    except Exception as exc:
        result = AudioAnalysis(status='error', message=f'音频分析失败: {exc}',
                               sample_rate=sample_rate, hop_length=hop_length)
    return result
