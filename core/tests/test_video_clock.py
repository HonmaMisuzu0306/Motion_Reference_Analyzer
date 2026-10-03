"""Audio/cuts/representative/CV/OCR frames must share a video-relative clock."""
import pytest

from audio.analyzer import analyze_audio
from audio.rhythm import apply_rhythm
from cv.frame_sampler import sample_frames_for_cv
from ocr.frames import sample_ocr_frames
from schemas import Shot, TimeRange
from tests.test_audio import write_av_video
from video.decoder import extract_frame
from video.frame_sampler import sample_frames
from video.metadata import read_video_metadata
from video.scene_detect import detect_scenes


def test_nonzero_media_origin_keeps_cuts_frames_and_beats_aligned(tmp_path):
    source = write_av_video(tmp_path / 'shifted.mp4', origin=10)
    metadata = read_video_metadata(source)
    assert metadata['duration'] == pytest.approx(8, abs=.05)
    scenes = detect_scenes(source)
    assert [(s['start'], s['end']) for s in scenes] == [(0, 2), (2, 4), (4, 6), (6, 8)]
    audio = analyze_audio(source)
    shots = [Shot(shot_id=s['shot_id'], time=TimeRange(**s),
                  provider_versions={'video_clock': {'version': 'video-relative-v1'}}) for s in scenes]
    summary = apply_rhythm(shots, audio)
    assert summary.synced_cut_count == 3
    # Relative second shot is bright. Seeking raw2s instead of raw12s picks dark first frame.
    representative = sample_frames(source, 2, 4)
    cv = sample_frames_for_cv(source, 2, 3.9)
    ocr = sample_ocr_frames(source, 2, 4)
    assert representative and cv and ocr
    assert all(frame['image'].mean() > 200 for frame in representative + cv + ocr)
    assert all(2 <= frame['timestamp'] <= 4 for frame in representative + cv + ocr)
    assert extract_frame(source, 2.5).mean() > 200


def test_playback_copy_normalizes_pts_without_changing_original_or_audio_offset(tmp_path):
    import av

    from video.playback import playback_source

    source = write_av_video(tmp_path / 'shifted.mp4', origin=10, offset=1.25)
    original = source.read_bytes()
    preview = playback_source(source, tmp_path / 'playback')
    assert preview != source and preview.exists()
    assert source.read_bytes() == original
    with av.open(str(preview)) as container:
        video = container.streams.video[0]
        assert float(video.start_time * video.time_base) == pytest.approx(0, abs=.001)
        assert float(video.duration * video.time_base) == pytest.approx(8, abs=.05)
    assert analyze_audio(preview).onset_times[0] == pytest.approx(1.75, abs=.08)
    assert sample_frames(preview, 2, 4)[0]['image'].mean() > 200
    assert playback_source(source, tmp_path / 'playback') == preview
    normal = write_av_video(tmp_path / 'normal.mp4')
    assert playback_source(normal, tmp_path / 'playback') == normal
