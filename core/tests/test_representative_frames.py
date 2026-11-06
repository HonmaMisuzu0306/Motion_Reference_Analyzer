"""Actual presentation times and strict shot ownership for visual evidence."""
from fractions import Fraction
from math import nextafter
from types import SimpleNamespace

import av
import numpy as np
import pytest
from PIL import Image

from cv.frame_sampler import sample_frames_for_cv
from ocr.semantic import TypographySemanticAnalyzer
from schemas.typography import TextRegion, TextTrack, TypographyAnalysis
from selection.frames import iter_range_frames, locate_frame
from selection.media import detect_range_scenes, sample_range_frames
from tests.test_scene_motion import write_frames
from tests.test_selection_frames import write_vfr
from video.frame_sampler import create_contact_sheet, sample_frames
from video.scene_detect import detect_scenes
from video.timing import relative_frame_time


def decoded_times(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        origin = stream.start_time * stream.time_base if stream.start_time is not None else 0
        return [float(frame.pts * frame.time_base - origin) for frame in container.decode(stream)]


@pytest.mark.parametrize('origin', [0, 10])
def test_real_24fps_cut_is_owned_by_only_the_following_shot(tmp_path, origin):
    dark = np.full((64, 96, 3), 10, np.uint8)
    light = np.full_like(dark, 240)
    path = write_frames(tmp_path / 'cut.mp4', [dark] * 10 + [light] * 14, origin=origin)
    times = decoded_times(path)
    scenes = detect_scenes(path)
    assert len(scenes) == 2
    assert scenes[0]['end'] == scenes[1]['start'] == times[10]
    assert scenes[0]['end'] != round(times[10], 3)
    first = sample_frames(path, scenes[0]['start'], scenes[0]['end'], count=30)
    second = sample_frames(path, scenes[1]['start'], scenes[1]['end'], count=40)
    assert [frame['timestamp'] for frame in first] == times[:10]
    assert [frame['timestamp'] for frame in second] == times[10:]
    assert all(frame['image'].mean() < 20 for frame in first)
    assert all(frame['image'].mean() > 230 for frame in second)
    selected = detect_range_scenes(path, 0, 1)
    assert selected[0].end == selected[1].start == times[10]


@pytest.mark.parametrize('origin', [0, 10])
def test_literal_fractional_start_is_exact_even_with_nonzero_source_origin(tmp_path, origin):
    path = write_frames(tmp_path / 'literal-start.mp4',
                        [np.full((64, 96, 3), i * 10, np.uint8) for i in range(24)], origin=origin)
    start, end = 10 / 24, 11 / 24
    assert [frame['timestamp'] for frame in sample_frames(path, start, end)] == [start]
    assert [frame['timestamp'] for frame in sample_frames_for_cv(path, start, end, target_fps=24)] == [start]
    assert [frame.identity.actual_time for frame in iter_range_frames(path, start, end)] == [start]
    assert locate_frame(path, nextafter(start, -float('inf'))).identity.actual_time == 9 / 24
    assert locate_frame(path, start).identity.actual_time == start
    assert [frame.identity.actual_time for frame in iter_range_frames(path, start, nextafter(start, float('inf')))] == [start]
    assert list(iter_range_frames(path, nextafter(start, float('inf')), end)) == []


def test_relative_clock_keeps_rationals_until_origin_is_removed():
    stream = SimpleNamespace(start_time=240000, time_base=Fraction(1, 24000))
    assert relative_frame_time(stream, 250000) == 10 / 24
    assert relative_frame_time(stream, 12500, Fraction(1, 1200)) == 10 / 24
    stream.start_time = None
    assert relative_frame_time(stream, 10000) == 10 / 24
    with pytest.raises(ValueError, match='实际时间戳'):
        relative_frame_time(stream, None)


@pytest.mark.parametrize('origin', [0, 10])
def test_one_float_wide_range_keeps_its_exact_start_and_deduplicates(tmp_path, origin):
    path = write_frames(tmp_path / 'tiny.mp4', [np.full((64, 96, 3), i * 10, np.uint8) for i in range(24)], origin=origin)
    timestamp = decoded_times(path)[10]
    frames = sample_frames(path, timestamp, nextafter(timestamp, float('inf')), count=5)
    assert [frame['timestamp'] for frame in frames] == [timestamp]
    assert frames[0]['image'].mean() == pytest.approx(100, abs=4)


def test_vfr_returns_actual_unique_times_and_never_borrows_outside_range(tmp_path):
    path = write_vfr(tmp_path / 'vfr.mp4')
    frames = sample_frames(path, .04, .11, count=5)
    assert [frame['timestamp'] for frame in frames] == [.04]
    assert frames[0]['image'].mean() == pytest.approx(100, abs=4)
    for start, end in [(.05, .10), (nextafter(.04, float('inf')), .11), (.12, .13)]:
        with pytest.raises(RuntimeError, match='范围.*没有可解码帧'):
            sample_frames(path, start, end)


@pytest.mark.parametrize('start,end,count', [(0, 0, 1), (-1, 1, 1), (1, 0, 1),
                                            (float('nan'), 1, 1), (0, float('inf'), 1), (0, 1, 0)])
def test_invalid_representative_ranges_fail_before_opening_video(start, end, count):
    with pytest.raises(ValueError):
        sample_frames('unused.mp4', start, end, count)


@pytest.mark.parametrize('origin', [0, 10])
def test_selection_float_neighbors_do_not_widen_or_shrink_half_open_bounds(tmp_path, origin):
    path = write_frames(tmp_path / 'neighbors.mp4', [np.full((64, 96, 3), i * 10, np.uint8) for i in range(24)], origin=origin)
    times = decoded_times(path)
    point = times[10]
    before, after = nextafter(point, -float('inf')), nextafter(point, float('inf'))
    assert [frame.identity.actual_time for frame in iter_range_frames(path, point, after)] == [point]
    assert list(iter_range_frames(path, after, times[11])) == []
    assert locate_frame(path, before).identity.actual_time == times[9]
    assert locate_frame(path, point).identity.actual_time == point
    assert [frame.identity.actual_time for frame in sample_range_frames(path, point, after, 3)] == [point]
    left = list(iter_range_frames(path, times[9], point))
    right = list(iter_range_frames(path, point, times[11]))
    assert [frame.identity.actual_time for frame in left + right] == times[9:11]


def test_fractional_frame_rate_preserves_actual_unrounded_timestamps(tmp_path):
    path = tmp_path / 'fractional.mp4'
    rate = Fraction(24000, 1001)
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=rate)
        stream.width, stream.height, stream.pix_fmt = 96, 64, 'yuv420p'
        for i in range(24):
            frame = av.VideoFrame.from_ndarray(np.full((64, 96, 3), i * 10, np.uint8), format='bgr24')
            frame.pts, frame.time_base = i, 1 / rate
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    times = decoded_times(path)
    frames = sample_frames(path, times[9], times[11], count=8)
    assert [frame['timestamp'] for frame in frames] == times[9:11]
    assert frames[1]['timestamp'] != round(frames[1]['timestamp'], 3)


def test_contact_sheet_converts_bgr_red_and_blue_to_correct_rgb(tmp_path):
    red_bgr = np.full((16, 16, 3), (0, 0, 255), np.uint8)
    blue_bgr = np.full((16, 16, 3), (255, 0, 0), np.uint8)
    path = create_contact_sheet([red_bgr, blue_bgr], tmp_path / 'colors.png')
    with Image.open(path) as image:
        assert image.getpixel((8, 8)) == (255, 0, 0)
        assert image.getpixel((24, 8)) == (0, 0, 255)


def test_typography_revisit_uses_exact_pts_names_and_actual_observation_time(tmp_path):
    path = tmp_path / 'close_pts.mp4'
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=25)
        stream.width, stream.height, stream.pix_fmt = 96, 64, 'yuv420p'
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1_000_000)
        stream.codec_context.max_b_frames = 0
        for pts, color in [(0, (0, 0, 0)), (40100, (0, 0, 255)), (40200, (255, 0, 0)), (110000, (0, 0, 0))]:
            frame = av.VideoFrame.from_ndarray(np.full((64, 96, 3), color, np.uint8), format='bgr24')
            frame.pts, frame.time_base = pts, Fraction(1, 1_000_000)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    times = decoded_times(path)
    calls = []

    class Provider:
        def get_model_info(self):
            return {'model': 'test'}

        def analyze_text_region(self, image_path, bbox, text, context):
            with Image.open(image_path) as image:
                calls.append((image_path, image.getpixel((48, 32)), context))
            return TypographyAnalysis(confidence=.9)

    tracks = [TextTrack(track_id=str(i), average_confidence=.9, start_time=0,
                        regions=[TextRegion(frame_timestamp=timestamp, confidence=.9, text='test')])
              for i, timestamp in enumerate(times[1:3])]
    TypographySemanticAnalyzer(Provider()).analyze_tracks(tracks, tmp_path / 'representative.jpg', 'shot', path)
    assert len(calls) == 2 and calls[0][0] != calls[1][0]
    assert calls[0][1][0] > 220 and calls[0][1][2] < 30
    assert calls[1][1][2] > 220 and calls[1][1][0] < 30
    assert [call[2]['timestamp'] for call in calls] == times[1:3]
