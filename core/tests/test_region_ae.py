import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cv.region_track import RegionSample, RegionTrack
from recipe.region_ae import export_region_ae_script


def track():
    return RegionTrack(status='complete', frame_width=360, frame_height=640, samples=[
        RegionSample(source_time=t, center_x_px=x, center_y_px=y)
        for t, x, y in [(12.025, 21.5, 500), (12.173, 42.25, 480.125), (12.3, 30, 511)]
    ])


@pytest.mark.parametrize(('partial', 'source_fps', 'host_limit', 'comp_fps'),
                         [(False, 25, 99, 25), (True, 25, 99, 25), (True, 200, 99, 200 / 3)])
def test_script_places_one_null_on_the_confirmed_prefix(tmp_path, partial, source_fps, host_limit, comp_fps):
    trajectory = track()
    if partial:
        trajectory.status, trajectory.stop_time = 'no_match', 12.31
    path = export_region_ae_script(trajectory, source_start=12, source_end=23, fps=source_fps,
                                   path=tmp_path / 'region.jsx')
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required to execute the ExtendScript contract test')
    mock = Path(__file__).parent / 'fixtures/ae_mock.cjs'
    result = subprocess.run([node, str(mock), str(path), str(host_limit)], check=True, capture_output=True,
                            text=True, encoding='utf-8', timeout=5)
    state = json.loads(result.stdout)
    assert state['alerts'] == []
    assert state['undoStart'] == state['undoEnd'] == 1
    comp, = state['comps']
    assert [comp['width'], comp['height'], comp['aspect']] == [360, 640, 1]
    assert comp['fps'] == pytest.approx(comp_fps)
    assert '12.025' in comp['comment'] and '12.3' in comp['comment']
    if partial:
        assert '12.31' in comp['comment'] and 'no_match' in comp['comment']
    if comp_fps != source_fps:
        assert 'Source 200 fps' in comp['comment']
    layer, = comp['entries']
    assert layer['nullLayer'] and not layer['threeDLayer']
    end = min(12.31 if partial else 23, 12.3 + 1 / source_fps) - 12.025
    assert layer['outPoint'] == pytest.approx(end)
    assert end - 1e-8 <= comp['duration'] < end + 1 / comp_fps + 1e-8
    assert set(layer['props']) == {'ADBE Position'}
    pos = layer['props']['ADBE Position']
    assert pos['dimensionsSeparated']
    for dim, values in enumerate(([21.5, 42.25, 30], [500, 480.125, 511])):
        keys = pos['followers'][str(dim)]['keys']
        assert [key['time'] for key in keys] == pytest.approx([0, .148, .275])
        assert [key['value'] for key in keys] == values
        assert all(key['interpolation'] == ['linear', 'linear'] for key in keys)


@pytest.mark.parametrize('invalid', ['single', 'NaN', 'out_of_frame', 'before_start', 'time_gap', 'duplicate',
                                     'unsound_status', 'missing_stop', 'stop_order', 'size', 'fps', 'raw_dict'])
def test_no_file_for_invalid_or_unconfirmed_data(tmp_path, invalid):
    value = track()
    fps = 24
    if invalid == 'single':
        value.samples = value.samples[:1]
    elif invalid == 'NaN':
        value.samples[0].center_y_px = float('nan')
    elif invalid == 'out_of_frame':
        value.samples[1].center_x_px = 361
    elif invalid == 'before_start':
        value.samples[0].source_time = 11.9
    elif invalid == 'time_gap':
        value.samples[-1].source_time = 13
    elif invalid == 'duplicate':
        value.samples[-1].source_time = value.samples[-2].source_time
    elif invalid == 'unsound_status':
        value.status, value.stop_time = 'anchor_mismatch', 12.35
    elif invalid == 'missing_stop':
        value.status = 'ambiguous'
    elif invalid == 'stop_order':
        value.status, value.stop_time = 'no_match', 12.3
    elif invalid == 'size':
        value.frame_width = 0
    elif invalid == 'fps':
        fps = 10**1000
    elif invalid == 'raw_dict':
        value = value.model_dump()
    path = tmp_path / 'invalid' / 'track.jsx'
    with pytest.raises(ValueError):
        export_region_ae_script(value, source_start=12, source_end=14, fps=fps, path=path)
    assert not path.parent.exists()
