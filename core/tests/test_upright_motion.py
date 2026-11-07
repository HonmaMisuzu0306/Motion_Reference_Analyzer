"""The player, OCR evidence, measured motion and exported AE comp use the same upright image."""
import json
import re
from pathlib import Path

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import reset_config
from app.main import app
from cv.frame_sampler import sample_frames_for_cv
from ocr.frames import sample_ocr_frames
from selection.frames import locate_frame
from tests.test_motion_benchmark import benchmark
from tests.test_selection_api import wait_done


@pytest.fixture
def rotated_pan(tmp_path):
    # Both files contain the same compressed frames. Only the display matrix changes.
    source = benchmark.generate_case(tmp_path, 'out_and_back', duration=.5)['video_path']
    tagged = tmp_path / 'upright.mp4'
    with av.open(str(source)) as original, av.open(str(tagged), 'w') as output:
        stream = original.streams.video[0]
        destination = output.add_stream_from_template(stream)
        destination.set_display_rotation(90)
        for packet in original.demux(stream):
            if packet.dts is not None:
                packet.stream = destination
                output.mux(packet)
    return Path(source), tagged


def test_selection_ocr_and_cv_agree_on_upright_pixels(rotated_pan):
    original, tagged = rotated_pan
    raw = locate_frame(original, 0)
    upright = locate_frame(tagged, 0)
    assert upright.identity.actual_time == raw.identity.actual_time == 0
    np.testing.assert_array_equal(upright.image, np.rot90(raw.image))
    sampled = sample_frames_for_cv(tagged, 0, .5)
    assert sampled[0]['image'].shape[:2] == (320, 180)
    np.testing.assert_array_equal(sampled[0]['image'], upright.image)
    for strict in (False, True):
        plain = sample_ocr_frames(original, 0, .5, strict_range=strict)
        oriented = sample_ocr_frames(tagged, 0, .5, strict_range=strict)
        assert [v['timestamp'] for v in oriented] == [v['timestamp'] for v in plain]
        for before, after in zip(plain, oriented, strict=True):
            assert (after['width'], after['height']) == (180, 320)
            np.testing.assert_array_equal(after['image'], np.rot90(before['image']))


def check_vertical_plan(shot):
    measured = shot['measured_motion']
    assert measured['trajectory_status'] == 'complete'
    assert (measured['frame_width'], measured['frame_height']) == (180, 320)
    curves = shot['ae_recipe']['animation_plan']['curves']
    assert not any(c['property'] == 'position_x' for c in curves)
    points = next(c['points'] for c in curves if c['property'] == 'position_y')
    assert -21 < min(p['value'] for p in points) < -18
    assert abs(points[-1]['value']) < .5


def check_export(client, route):
    response = client.post(route)
    assert response.status_code == 200, response.text
    script = Path(response.json()['path']).read_text(encoding='utf8')
    setup = json.loads(re.search(r'    var data = (.+);\n', script)[1])
    assert (setup['width'], setup['height']) == (180, 320)
    assert any(c['property'] == 'position_y' for c in setup['curves'])


def test_import_analysis_and_selection_export_upright_motion(rotated_pan, monkeypatch):
    _, tagged = rotated_pan
    monkeypatch.setenv('VISION_PROVIDER', 'mock')
    monkeypatch.setenv('OCR_PROVIDER', 'mock')
    reset_config()
    with TestClient(app) as client:
        imported = client.post('/api/v1/video/import', json={'path': str(tagged)})
        assert imported.status_code == 200, imported.text
        video = imported.json()['video']
        assert (video['width'], video['height']) == (180, 320)
        analyzed = client.post('/api/v1/video/analyze', json={'mode': 'basic'})
        assert analyzed.status_code == 200, analyzed.text
        shot, = client.get('/api/v1/shots').json()['shots']
        check_vertical_plan(shot)
        check_export(client, '/api/v1/shots/' + shot['shot_id'] + '/export/ae')
        pid = client.post('/api/v1/project/save').json()['project_id']
        response = client.post(f'/api/v1/projects/{pid}/selection-analyses',
                               json={'kind': 'clip', 'start': 0, 'end': .5})
        assert response.status_code == 202, response.text
        rid = response.json()['record_id']
        record = wait_done(client, rid)
        assert record['status'] in ('done', 'completed_with_warnings'), record
        local_shot, = record['result']['shots']
        check_vertical_plan(local_shot)
        check_export(client, f"/api/v1/selection-analyses/{rid}/shots/{local_shot['shot_id']}/export/ae")
