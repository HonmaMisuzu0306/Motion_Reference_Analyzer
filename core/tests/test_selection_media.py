"""Half-open evidence and range-only audio on the original video clock."""
import pytest

from cv.frame_sampler import sample_frames_for_cv
from ocr.frames import sample_ocr_frames
from selection.media import analyze_range_audio, detect_range_scenes, sample_range_frames
from tests.test_audio import write_av_video
from tests.test_selection_frames import write_vfr


def test_range_cuts_preserve_short_first_and_last_shots(tmp_path):
    path = write_av_video(tmp_path / 'cuts.mp4')
    scenes = detect_range_scenes(path, 1.9, 6.1)
    assert [(s.start, s.end) for s in scenes] == [(1.9, 2), (2, 4), (4, 6), (6, 6.1)]
    for scene in scenes:
        frames = sample_range_frames(path, scene.start, scene.end, 3)
        assert frames and all(scene.start <= f.identity.actual_time < scene.end for f in frames)


def test_cv_excludes_end_and_ocr_uses_real_unique_pts(tmp_path):
    path = write_av_video(tmp_path / 'clock.mp4', duration=1, audio=False)
    assert all(f['timestamp'] < .5 for f in sample_frames_for_cv(path, 0, .5, target_fps=24))
    vfr = write_vfr(tmp_path / 'vfr.mp4')
    frames = sample_ocr_frames(vfr, .04, .11, strict_range=True)
    assert len(frames) == 1 and frames[0]['timestamp'] == pytest.approx(.04)
    assert sample_range_frames(vfr, .05, .10, 3) == []


def test_short_range_has_source_onsets_without_inventing_bpm(tmp_path):
    path = write_av_video(tmp_path / 'delayed.mp4', origin=10, offset=1.25, duration=16)
    result = analyze_range_audio(path, 2, 6)
    assert result.status == 'insufficient' and result.tempo_bpm is None and result.beat_times == []
    assert result.duration == pytest.approx(4) and result.waveform
    assert all(2 <= p.time < 6 for p in result.waveform)
    assert result.onset_times[0] == pytest.approx(2.25, abs=.08)
    longer = analyze_range_audio(path, 2, 14)
    assert longer.status == 'ok' and longer.tempo_bpm == pytest.approx(120, abs=4)
    assert longer.beat_times and all(2 <= t < 14 for t in longer.beat_times)


@pytest.mark.parametrize('audio,silent,status', [(False, False, 'no_audio'), (True, True, 'silent')])
def test_no_audio_and_silent_remain_distinct(tmp_path, audio, silent, status):
    path = write_av_video(tmp_path / 'input.mp4', audio=audio, silent=silent)
    assert analyze_range_audio(path, 1, 5).status == status
