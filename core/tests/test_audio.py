"""Real audio detection, media timing and cache identity contracts."""
import os
import wave
from fractions import Fraction

import av
import numpy as np
import pytest


def click_signal(duration=12, sr=22050):
    y = np.zeros(int(duration * sr), dtype=np.float32)
    pulse = .8 * np.sin(2 * np.pi * 1000 * np.arange(int(.03 * sr)) / sr)
    pulse *= np.exp(-np.arange(len(pulse)) / (sr * .007))
    for t in np.arange(.5, duration - .1, .5):
        at = round(t * sr)
        y[at:at + len(pulse)] += pulse
    return y


def write_wav(path, y, sr=22050):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((y * 32767).astype('<i2').tobytes())
    return path


def write_av_video(path, *, audio=True, silent=False, offset=0.0, duration=8, cuts=(2, 4, 6), origin=0):
    """MP4 with video cut at2/4/6s and AAC clicks; real encoded media, no model stub."""
    sr, fps = 44100, 24
    with av.open(str(path), 'w') as out:
        video = out.add_stream('libx264', rate=fps)
        video.width, video.height, video.pix_fmt = 160, 120, 'yuv420p'
        sound = out.add_stream('aac', rate=sr) if audio else None
        if sound:
            sound.layout = 'mono'
        for i in range(int(duration * fps)):
            value = 240 if sum(i / fps >= t for t in cuts) % 2 else 10
            frame = av.VideoFrame.from_ndarray(np.full((120, 160, 3), value, np.uint8), format='rgb24')
            frame.pts, frame.time_base = i + round(origin * fps), Fraction(1, fps)
            for p in video.encode(frame):
                out.mux(p)
        for p in video.encode():
            out.mux(p)
        if sound:
            y = np.zeros(int((duration - offset) * sr), np.float32) if silent else click_signal(duration - offset, sr)
            for i in range(0, len(y), 1024):
                frame = av.AudioFrame.from_ndarray(y[None, i:i + 1024], format='fltp', layout='mono')
                frame.sample_rate = sr
                frame.pts, frame.time_base = i + round((offset + origin) * sr), Fraction(1, sr)
                for p in sound.encode(frame):
                    out.mux(p)
            for p in sound.encode():
                out.mux(p)
    return path


def test_real_clicks_detect_120_bpm_and_onsets(tmp_path):
    from audio.analyzer import analyze_audio

    path = write_wav(tmp_path / 'click.wav', click_signal())
    result = analyze_audio(path)
    assert result.status == 'ok'
    assert result.tempo_bpm == pytest.approx(120, abs=4)
    assert len(result.beat_times) >= 18
    assert len(result.onset_times) >= 21
    assert min(abs(t - 5) for t in result.beat_times) < .08
    assert result.beat_times == sorted(set(result.beat_times))
    assert result.waveform and max(p.rms for p in result.waveform) > 0
    assert result.duration == pytest.approx(12, abs=.01)


@pytest.mark.parametrize('y,status', [(np.zeros(22050, np.float32), 'silent'),
                                     (np.ones(100, np.float32) * .2, 'insufficient')])
def test_silence_and_short_audio_do_not_invent_beats(tmp_path, y, status):
    from audio.analyzer import analyze_audio

    result = analyze_audio(write_wav(tmp_path / 'input.wav', y))
    assert result.status == status
    assert result.beat_times == [] and result.tempo_bpm is None


def test_no_audio_video_and_corrupt_media_have_distinct_states(tmp_path):
    from audio.analyzer import analyze_audio

    assert analyze_audio(write_av_video(tmp_path / 'mute.mp4', audio=False, duration=1)).status == 'no_audio'
    bad = tmp_path / 'broken.mp4'
    bad.write_bytes(b'not media')
    assert analyze_audio(bad).status == 'error'


def test_delayed_audio_remains_on_video_clock(tmp_path):
    from audio.analyzer import analyze_audio

    result = analyze_audio(write_av_video(tmp_path / 'late.mp4', offset=1.25))
    assert result.status == 'ok'
    # First click at 0.5 relative to the audio, hence 1.75 on the video timeline.
    assert result.onset_times[0] == pytest.approx(1.75, abs=.08)
    assert min(abs(t - 3.25) for t in result.beat_times) < .08
    assert all(p.rms == 0 for p in result.waveform if p.time < 1.1)


def test_duration_limit_rejects_media_instead_of_silent_truncation(tmp_path):
    from audio.analyzer import analyze_audio

    result = analyze_audio(write_wav(tmp_path / 'long.wav', click_signal(4)), max_duration=2)
    assert result.status == 'error'
    assert '2' in result.message
    assert not result.beat_times


def test_cache_uses_content_config_and_recovers_from_corruption(tmp_path, monkeypatch):
    from audio.analyzer import analyze_audio
    from audio.cache import AudioCache

    path = write_wav(tmp_path / 'same.wav', click_signal(4))
    cache = AudioCache(tmp_path / 'cache')
    first = analyze_audio(path, cache=cache)
    assert not first.cache_hit and first.status == 'ok'
    assert analyze_audio(path, cache=cache).cache_hit
    # A same-size same-name same-mtime replacement must not reuse the previous beats.
    stamp = path.stat()
    write_wav(path, np.zeros(4 * 22050, np.float32))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    silence = analyze_audio(path, cache=cache)
    assert silence.status == 'silent' and not silence.cache_hit
    assert not analyze_audio(path, cache=cache, hop_length=512).cache_hit
    for file in cache.cache_dir.glob('*.json'):
        file.write_text('{broken', encoding='utf-8')
    assert not analyze_audio(path, cache=cache).cache_hit


def test_cut_matching_signed_delta_threshold_ties_and_no_beats():
    from audio.rhythm import match_cut
    from schemas.audio import AudioAnalysis

    audio = AudioAnalysis(status='ok', beat_times=[1, 1.5, 2], onset_times=[1.2])
    assert match_cut(1.024, audio).delta_ms == 24
    assert match_cut(1.024, audio).beat_sync is True
    assert match_cut(.95, audio).delta_ms == -50
    assert match_cut(1.08, audio).beat_sync is True
    assert match_cut(1.081, audio).beat_sync is False
    assert match_cut(1.25, audio).nearest_beat == 1  # deterministic earlier tie
    empty = match_cut(1.2, AudioAnalysis(status='ok', onset_times=[1.2]))
    assert empty.nearest_beat is None and empty.beat_sync is None
    assert empty.nearest_onset == 1.2  # onset never stands in for a beat
