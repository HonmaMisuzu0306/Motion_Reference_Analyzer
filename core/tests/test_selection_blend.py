from fractions import Fraction

import av
import cv2
import numpy as np
import pytest

from selection.blend import MAX_FRAMES, BlendSamples
from selection.export import export_selection
from selection.models import SelectionRequest
from selection.pipeline import run_selection
from tests.test_selection_pipeline import snapshot


def plates():
    rng = np.random.default_rng(104)
    return [cv2.resize(rng.integers(10, 240, (12, 16, 3), np.uint8), (144, 108),
                       interpolation=cv2.INTER_CUBIC) for _ in range(2)]


def weight(time):
    t = float(np.clip((time - .5) / .9, 0, 1))
    return t * t * (3 - 2 * t)


def test_nonzero_vfr_selection_to_production_advice(tmp_path):
    path = tmp_path / 'vfr.mp4'
    a, b = plates()
    ticks = np.cumsum([0] + [2, 3, 3] * 15)
    with av.open(str(path), 'w') as out:
        stream = out.add_stream('libx264', rate=60)
        stream.width, stream.height, stream.pix_fmt = 144, 108, 'yuv420p'
        for tick in ticks:
            w = weight(tick / 60)
            frame = av.VideoFrame.from_ndarray(cv2.addWeighted(a, 1 - w, b, w, 0), format='bgr24')
            frame.pts, frame.time_base = 600 + int(tick), Fraction(1, 60)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    request = SelectionRequest(kind='clip', start=.21, end=1.83)
    result = run_selection(snapshot(tmp_path, path, request), lambda *args: None)
    assert len(result['shots']) == 1
    blend = result['opacity_blend']
    keys = blend['keyframes']
    expected_times = [float(t / 60) for t in ticks if request.start <= t / 60 < request.end]
    measured_times = [k['source_time'] for k in keys]
    assert set(measured_times).issubset(expected_times)
    ends = dict(zip(expected_times, expected_times[1:] + [request.end]))
    assert all(k['frame_end'] == ends[k['source_time']] for k in keys)
    assert blend['sample_count'] == len(expected_times)
    assert measured_times[0] == expected_times[0] and measured_times[-1] == expected_times[-1]
    estimate = np.interp(expected_times, measured_times, [k['opacity_percent'] for k in keys])
    assert max(abs(estimate - [100 * weight(t) for t in expected_times])) < 2.5
    record = dict(id='test', kind='clip', source_hash=result['source_hash'], status='done', result=result)
    report = export_selection(record, 'markdown', tmp_path).read_text(encoding='utf-8')
    for key in keys:
        t = key['source_time']
        assert f"| {t:.3f} | {t - request.start:.3f} | {key['opacity_percent']:.1f}% |" in report


@pytest.mark.parametrize('case', ['trim_head', 'trim_tail', 'gain', 'gamma', 'plain', 'logo',
                                  'wipe', 'hard_cut', 'moving_patch', 'reverse', 'gap'])
def test_inconclusive_transitions_emit_no_opacity_curve(case):
    a, b = plates()
    if case == 'gain':
        b = np.rint(a * .45).astype(np.uint8)
    if case == 'gamma':
        b = np.rint(255 * (a / 255) ** 3).astype(np.uint8)
    if case == 'plain':
        b = np.full_like(a, [20, 40, 220])
    if case == 'logo':
        patch = b[:28, :36].copy()
        b = a.copy()
        b[:28, :36] = patch
    samples = BlendSamples()
    for i in range(48):
        time = i / 24
        if (case == 'trim_head' and time < .75) or (case == 'trim_tail' and time > 1.20):
            continue
        if case == 'gap' and 18 < i < 25:
            continue
        w = weight(time)
        if case == 'hard_cut':
            w = float(i >= 24)
        if case == 'reverse' and 22 <= i <= 26:
            w = weight((44 - i) / 24)
        frame = cv2.addWeighted(a, 1 - w, b, w, 0)
        if case == 'moving_patch' and i == 24:
            frame[:30, :32] = 240
        if case == 'wipe':
            x = round(w * a.shape[1])
            frame = a.copy()
            frame[:, :x] = b[:, :x]
        samples.add(time, frame)
    assert samples.estimate() is None


def test_frame_limit_discards_overlong_buffer():
    a, _ = plates()
    samples = BlendSamples()
    for i in range(MAX_FRAMES + 1):
        samples.add(i / 120, a)
    assert not samples.pictures
    assert samples.estimate() is None


@pytest.mark.parametrize('case', ['independent', 'reversed', 'caption', 'vignette', 'warm_spot'])
def test_lighting_changes_require_new_texture_throughout_the_frame(case):
    a, b = plates()
    a = np.rint(a * .45).astype('uint8')
    if case in ('independent', 'reversed'):
        b = np.rint(126 + b * .45).astype('uint8')
        if case == 'reversed':
            a, b = b, a
    else:
        b = 98 + 1.34 * a.astype(float)
        if case == 'caption':
            cv2.putText(b, 'TITLE', (12, 88), cv2.FONT_HERSHEY_SIMPLEX, .7, (10, 30, 22), 3)
        else:
            y, x = np.mgrid[-1:1:108j, -1:1:144j]
            field = np.maximum(0, 1 - (x - .2) ** 2 - (y + .12) ** 2)
            color = np.array([42, 76, 127]) if case == 'warm_spot' else 96
            b += (field[:, :, None] - .6) * color
        b = np.rint(b).clip(0, 255).astype('uint8')
    samples = BlendSamples()
    for i in range(48):
        t = i / 24
        w = weight(t)
        samples.add(t, cv2.addWeighted(a, 1 - w, b, w, 0))
    result = samples.estimate(2)
    if case in ('independent', 'reversed'):
        assert result is not None
        keys = result['keyframes']
        actual = np.interp(samples.times, [k['source_time'] for k in keys], [k['opacity_percent'] for k in keys])
        assert max(abs(actual - [100 * weight(t) for t in samples.times])) < 1.6
    else:
        assert result is None


def test_dedicated_measurement_validates_range_and_skips_model_initialization(tmp_path, monkeypatch):
    from tests.test_audio import write_av_video

    with pytest.raises(ValueError, match='6秒'):
        SelectionRequest(kind='clip', measurement='opacity_blend', start=1, end=7.5)
    with pytest.raises(ValueError, match='视频选区'):
        SelectionRequest(kind='frame', measurement='opacity_blend')

    def unexpected(*args):
        raise AssertionError('pixel-only job tried to load a model')

    monkeypatch.setattr('selection.pipeline.create_vision_provider', unexpected)
    monkeypatch.setattr('selection.pipeline.create_ocr_provider', unexpected)
    path = write_av_video(tmp_path / 'cut.mp4', duration=2, cuts=(1,))
    request = SelectionRequest(kind='clip', measurement='opacity_blend', start=.25, end=1.75)
    result = run_selection(snapshot(tmp_path, path, request), lambda *args: None)
    assert 'opacity_blend' not in result and '切镜' in result['measurement_message']
