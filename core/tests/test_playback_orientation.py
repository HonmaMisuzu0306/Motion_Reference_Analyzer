"""Verify display-matrix bytes and A/V presentation clocks across the browser remux."""
import hashlib

import av
import pytest

from tests.test_audio import write_av_video
from video.playback import playback_source


def tracks(path):
    with av.open(str(path)) as media:
        video = media.streams.video[0]
        origin = video.start_time * video.time_base
        matrix = video.codec_context.coded_side_data['display_matrix']
        pictures = [(frame.pts * frame.time_base - origin,
                     hashlib.sha256(frame.to_ndarray(format='bgr24')).digest())
                    for frame in media.decode(video)]
    with av.open(str(path)) as media:
        audio = [(float(packet.pts * packet.time_base - origin), hashlib.sha256(bytes(packet)).digest())
                 for packet in media.demux(media.streams.audio[0]) if packet.size]
    return origin, matrix, pictures, audio


@pytest.mark.parametrize(('container', 'hflip'), [('mp4', False), ('mkv', True)])
def test_remux_preserves_rotated_picture_and_relative_audio_clock(tmp_path, container, hflip):
    source = write_av_video(tmp_path / f'nonzero.{container}', origin=10, rotation=90, hflip=hflip,
                            offset=.25, duration=2, cuts=(1,))
    if container == 'mkv':
        # Matroska H.264 has real leading B-frame reorder packets without DTS.
        with av.open(str(source)) as media:
            key = next(media.demux(video=0))
            assert key.is_keyframe and key.dts is None and key.pts is not None and key.size > 0
    cache = tmp_path / 'preview'
    cache.mkdir()
    stale = cache / (hashlib.sha256(source.read_bytes()).hexdigest() + '-video-clock-v1.mp4')
    stale.write_bytes(b'legacy-preview-with-dropped-keyframe')
    preview = playback_source(source, cache)
    assert preview != stale
    origin, matrix, frames, audio = tracks(source)
    new_origin, new_matrix, new_frames, new_audio = tracks(preview)
    assert origin == 10 and new_origin == 0
    assert len(frames) == 48 and new_frames == frames
    assert len(matrix) == 36 and new_matrix == matrix
    assert [payload for _, payload in audio] == [payload for _, payload in new_audio]
    assert [time for time, _ in new_audio] == pytest.approx([time for time, _ in audio], abs=1 / 44100)
