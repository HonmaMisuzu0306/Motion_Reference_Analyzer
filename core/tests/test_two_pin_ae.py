import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from cv.two_pin import TwoPinSample, TwoPinTrack
from recipe.two_pin_ae import export_two_pin_ae_script


def tracked(complete=True):
    delta_x, delta_y = 64, -38
    points = []
    for i, (t, angle, scale) in enumerate([(12.025, 0, 100), (12.17, 39, 92), (12.275, 73, 94),
                                           (12.40, 113, 106), (12.55, 150, 110), (12.73, 189, 107)]):
        a = (233.25 + 6*i, 301.75 - 5*i)
        theta = math.radians(angle)
        bx = a[0] + (delta_x*math.cos(theta) - delta_y*math.sin(theta))*scale/100
        by = a[1] + (delta_x*math.sin(theta) + delta_y*math.cos(theta))*scale/100
        points.append(TwoPinSample(source_time=t, position_x_px=a[0], position_y_px=a[1],
                                  pin_b_x_px=bx, pin_b_y_px=by, rotation_deg=angle, scale_percent=scale))
    return TwoPinTrack(status='complete' if complete else 'pin_lost', stop_time=None if complete else 12.743,
                       pin_a_status='complete', pin_b_status='complete' if complete else 'ambiguous',
                       frame_width=500, frame_height=750, initial_vector_x_px=delta_x, initial_vector_y_px=delta_y,
                       initial_distance_px=math.hypot(delta_x, delta_y), samples=points)


@pytest.mark.parametrize('complete,fps,host', [(True, 24, 99), (False, 24, 99), (False, 200, 99)])
def test_jsx_parent_and_child_reconstruct_both_measured_pins(tmp_path, complete, fps, host):
    track = tracked(complete)
    path = export_two_pin_ae_script(track, source_start=12, source_end=14, fps=fps, path=tmp_path/'pair.jsx')
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the ExtendScript contract test')
    mock = Path(__file__).parent/'fixtures/ae_mock.cjs'
    response = subprocess.run([node, str(mock), str(path), str(host)], capture_output=True, check=True,
                              text=True, encoding='utf8', timeout=5)
    state = json.loads(response.stdout)
    assert not state['alerts'] and state['undoStart'] == state['undoEnd'] == 1
    comp, = state['comps']
    assert (comp['width'], comp['height'], comp['aspect']) == (500, 750, 1)
    assert comp['fps'] == pytest.approx(fps / math.ceil(fps/host))
    root, child = comp['entries']
    assert child['parent'] == root and all(layer['nullLayer'] and not layer['threeDLayer'] for layer in (root,child))
    first = track.samples[0].source_time
    last = track.samples[-1].source_time
    limit = min(track.stop_time or 14, last + 1/fps) - first
    assert child['outPoint'] == root['outPoint'] == pytest.approx(limit)
    assert limit - 1e-8 <= comp['duration'] < limit + 1/comp['fps'] + 1e-8
    assert str(first) in comp['comment'] and str(last) in comp['comment']
    if not complete:
        assert str(track.stop_time) in comp['comment']
    a, b = root['props'], child['props']
    assert all(not prop['keys'] for prop in b.values())
    assert a['ADBE Anchor Point']['value'] == b['ADBE Anchor Point']['value'] == [0,0]
    assert b['ADBE Scale']['value'] == [100,100] and b['ADBE Rotate Z']['value'] == 0
    offset = b['ADBE Position']['value']
    x, y = (a['ADBE Position']['followers'][str(i)]['keys'] for i in range(2))
    rotation = a['ADBE Rotate Z']['keys']
    scale = a['ADBE Scale']['keys']
    for sample, kx, ky, kr, ks in zip(track.samples, x, y, rotation, scale, strict=True):
        assert all(k['time'] == pytest.approx(sample.source_time - first) and
                   k['interpolation'] == ['linear', 'linear'] for k in (kx, ky, kr, ks))
        assert [kx['value'], ky['value']] == pytest.approx([sample.position_x_px, sample.position_y_px])
        assert kr['value'] == pytest.approx(sample.rotation_deg)
        assert ks['value'] == pytest.approx([sample.scale_percent, sample.scale_percent])
        theta = math.radians(kr['value'])
        dx = offset[0]*ks['value'][0]/100
        dy = offset[1]*ks['value'][1]/100
        bx = kx['value'] + dx*math.cos(theta) - dy*math.sin(theta)
        by = ky['value'] + dx*math.sin(theta) + dy*math.cos(theta)
        assert [bx,by] == pytest.approx([sample.pin_b_x_px, sample.pin_b_y_px], abs=1e-8)


@pytest.mark.parametrize('invalid', ['raw_result', 'rotated_early', 'fake_B', 'flipped_vector', 'wrapped_angle',
                                      'duplicate_time', 'bad_stop', 'bad_pin_status', 'nan', 'short_track', 'bad_geometry',
                                      'raw_sample', 'collapsed_pair'])
def test_corrupt_or_unqualified_pin_data_never_creates_a_file(tmp_path, invalid):
    track = tracked()
    if invalid == 'raw_result':
        track = track.model_dump()
    elif invalid == 'rotated_early':
        track.samples[0].rotation_deg = 360
    elif invalid == 'fake_B':
        track.samples[-1].pin_b_x_px += 2
    elif invalid == 'flipped_vector':
        track.initial_vector_y_px *= -1
    elif invalid == 'wrapped_angle':
        track.samples[-1].rotation_deg -= 360
    elif invalid == 'duplicate_time':
        track.samples[-1].source_time = track.samples[-2].source_time
    elif invalid == 'bad_stop':
        track.status, track.stop_time = 'pin_lost', track.samples[-1].source_time
    elif invalid == 'bad_pin_status':
        track.pin_a_status = 'no_match'
    elif invalid == 'nan':
        track.samples[1].scale_percent = float('nan')
    elif invalid == 'short_track':
        track.samples = track.samples[:1]
    elif invalid == 'bad_geometry':
        track.frame_height = 2
    elif invalid == 'raw_sample':
        track.samples[0] = track.samples[0].model_dump()
    elif invalid == 'collapsed_pair':
        p = track.samples[-1]
        p.pin_b_x_px, p.pin_b_y_px = p.position_x_px, p.position_y_px
    path = tmp_path/'failed'/'not-created.jsx'
    with pytest.raises(ValueError):
        export_two_pin_ae_script(track, source_start=12, source_end=14, fps=24, path=path)
    assert not path.parent.exists()
