"""Cut timing relative to independently detected beat/onset events."""
from bisect import bisect_left
from statistics import median

from schemas.audio import AudioAnalysis, CutRhythm, RhythmSummary

VIDEO_CLOCK_VERSION = 'video-relative-v1'


def _nearest(time: float, events: list[float]) -> float | None:
    if not events:
        return None
    index = bisect_left(events, time)
    return min(events[max(0, index - 1):index + 1], key=lambda event: (abs(event - time), event))


def match_cut(cut_time: float, audio: AudioAnalysis, tolerance_ms: float = 80) -> CutRhythm:
    beat = _nearest(cut_time, audio.beat_times) if audio.status == 'ok' else None
    onset = _nearest(cut_time, audio.onset_times)
    delta = round((cut_time - beat) * 1000, 3) if beat is not None else None
    return CutRhythm(status='ok' if beat is not None else ('no_beats' if audio.status in {'ok', 'insufficient'} else 'unavailable'),
                     cut_time=cut_time, nearest_beat=beat, delta_ms=delta,
                     beat_sync=abs(delta) <= tolerance_ms if delta is not None else None,
                     nearest_onset=onset,
                     onset_delta_ms=round((cut_time - onset) * 1000, 3) if onset is not None else None,
                     tolerance_ms=tolerance_ms)


def apply_rhythm(shots, audio: AudioAnalysis, tolerance_ms: float = 80) -> RhythmSummary:
    compatible = []
    for shot in shots:
        clock = shot.provider_versions.get('video_clock', {})
        if audio.video_origin != 0 and clock.get('version') != VIDEO_CLOCK_VERSION:
            shot.rhythm = CutRhythm(status='unavailable', tolerance_ms=tolerance_ms,
                                    message='旧镜头的时间原点未经确认，请重新分析视频；此记录不参与节奏统计')
        else:
            compatible.append(shot)
    ordered = sorted(compatible, key=lambda shot: (shot.time.start, shot.time.end))
    cuts = []
    first_start = ordered[0].time.start if ordered else None
    # Library can retain historical versions; equal starts describe one cut.
    for shot in ordered:
        if shot.time.start == first_start:
            shot.rhythm = CutRhythm(status='not_cut', tolerance_ms=tolerance_ms)
        else:
            shot.rhythm = match_cut(shot.time.start, audio, tolerance_ms)
            if not cuts or cuts[-1].cut_time != shot.time.start:
                cuts.append(shot.rhythm)
    measured = [cut for cut in cuts if cut.delta_ms is not None]
    synced = sum(cut.beat_sync is True for cut in measured)
    return RhythmSummary(cut_count=len(cuts), measured_cut_count=len(measured),
                         synced_cut_count=synced, sync_ratio=synced / len(measured) if measured else None,
                         median_abs_delta_ms=median(abs(cut.delta_ms) for cut in measured) if measured else None,
                         tolerance_ms=tolerance_ms, excluded_shot_count=len(shots) - len(compatible))
