import av
import cv2
import numpy as np
import pytest

from selection.blend import BlendSamples
from selection.media import detect_range_scenes
from selection.models import SelectionRequest
from selection.pipeline import run_selection
from tests.test_selection_pipeline import snapshot


def _movie(path, *, linear=True, transfer=13, primaries=1, jump=0):
    rng = np.random.default_rng(3098)
    a, b = (cv2.resize(rng.uniform(0, 1, (14, 20, 3)), (160, 112)) for _ in range(2))
    a, b = .02 + .35*a, .61 + .36*b
    # On these plates all components lie above the sRGB linear toe.
    a, b = np.maximum(a, .044), np.maximum(b, .044)
    with av.open(str(path), 'w') as out:
        stream = out.add_stream('libx264', rate=24)
        stream.width, stream.height, stream.pix_fmt = 160, 112, 'yuv420p'
        stream.codec_context.color_trc, stream.codec_context.color_primaries = transfer, primaries
        stream.options = {'crf': '17'}
        for i in range(48):
            w = float(np.clip((i - 8) / 28, 0, 1))
            if i >= 9:
                w = min(1., jump + (1-jump)*w)
            if linear:
                # The two 1.055 scale factors cancel when expanded.
                rgb = ((1-w)*(a+.055)**2.4 + w*(b+.055)**2.4)**(1/2.4) - .055
            else:
                rgb = (1-w)*a + w*b
            frame = av.VideoFrame.from_ndarray(np.rint(255*rgb).astype('uint8'), format='bgr24')
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


@pytest.mark.parametrize('mode', ['decoded_rgb', 'srgb_linear'])
def test_recovers_authored_opacity_in_corresponding_blend_model(tmp_path, mode):
    path = tmp_path/'two-plates.mp4'
    _movie(path, linear=mode == 'srgb_linear')
    # Timeline cutting continues to flag this particular first linear-light step.
    cuts = [r.start for r in detect_range_scenes(path, 0, 2)]
    assert cuts == ([0, .375] if mode == 'srgb_linear' else [0])
    request = SelectionRequest(kind='clip', start=0., end=2., measurement='opacity_blend')
    result = run_selection(snapshot(tmp_path, path, request), lambda *args: None)['opacity_blend']
    assert result['sample_count'] == 48
    assert result['color_model'] == mode
    assert result['color_advice'] and result['model_rms'][mode] == min(result['model_rms'].values())
    keys = result['keyframes']
    reconstructed = np.interp(np.arange(48)/24, [k['source_time'] for k in keys], [k['opacity_percent'] for k in keys])
    expected = 100 * np.clip((np.arange(48)-8)/28, 0, 1)
    assert max(abs(reconstructed-expected)) < 2


@pytest.mark.parametrize('jump', [.035, .20])
def test_real_jump_into_smooth_linear_light_blend_keeps_boundary(tmp_path, jump):
    path = tmp_path/'jump-then-ramp.mp4'
    _movie(path, jump=jump)
    assert .375 in [r.start for r in detect_range_scenes(path, 0, 2)]
    request = SelectionRequest(kind='clip', start=0., end=2., measurement='opacity_blend')
    result = run_selection(snapshot(tmp_path, path, request), lambda *args: None)
    assert 'opacity_blend' not in result and '切镜' in result['measurement_message']


@pytest.mark.parametrize('transfer,primaries', [(16,9), (18,9), (13,12)])
def test_explicit_hdr_or_wide_gamut_does_not_get_sdr_advice(tmp_path, transfer, primaries):
    path = tmp_path/'tagged.mp4'
    _movie(path, transfer=transfer, primaries=primaries)
    samples = BlendSamples()
    detect_range_scenes(path, 0, 2, samples)
    assert samples.estimate(2) is None and 'SDR' in samples.skip_message
