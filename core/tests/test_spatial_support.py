"""A good local tracking fit is not evidence of a frame-wide transform."""
import av
import cv2
import numpy as np
import pytest

from cv.motion_analyzer import analyze_shot_motion
from cv.motion_fusion import fuse_motion
from cv.transform import _spatial_support
from recipe.ae_recipe import generate_ae_recipe


def write_pan(path, patches):
    # Same translation in every case, but different spatial extent of texture.
    width, height = 640, 360
    rng = np.random.default_rng(1104)
    texture = cv2.resize(rng.integers(10, 250, (90, 196, 3), dtype=np.uint8),
                         (784, height), interpolation=cv2.INTER_CUBIC)
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=24)
        stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
        for i in range(24):
            shift = 3 * i
            image = np.full((height, width, 3), 36, np.uint8)
            if patches is None:
                image[:] = texture[:, 100-shift:100-shift+width]
            else:
                for x, y, w, h in patches:
                    image[y:y+h, x+shift:x+shift+w] = texture[y:y+h, x:x+w]
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, 'bgr24')):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


@pytest.mark.parametrize(('patches', 'global_fit'), [
    ([(195, 121, 118, 88)], False),
    ([(24, 295, 400, 37)], False),
    ([(24, 30, 85, 75), (473, 35, 85, 75), (32, 240, 85, 75), (470, 240, 85, 75)], True),
    (None, True),
], ids=['central-patch', 'thin-lower-third', 'four-separated-patches', 'textured-plane'])
def test_export_requires_distributed_tracking(tmp_path, patches, global_fit):
    path = tmp_path / 'pan.mp4'
    write_pan(path, patches)
    motion = analyze_shot_motion(path, 0, 1, 640, 360)
    shot = {'time': {'start': 0, 'end': 1, 'duration': 1}, 'measured_motion': motion.model_dump()}
    plan = generate_ae_recipe(shot)['animation_plan']
    if global_fit:
        assert motion.status == 'ok'
        assert motion.translation_x_px == pytest.approx(69, abs=1)
        assert [c['property'] for c in plan['curves']] == ['position_x']
        assert motion.spatially_limited_pair_count == 0
    else:
        assert motion.status == 'localized_support'
        assert motion.spatially_limited_pair_count == motion.total_pair_count > 0
        assert motion.valid_pair_count == 0 and not motion.trajectory
        assert all(p.inlier_ratio > .9 and p.support_area_ratio < .15 for p in motion.pairs)
        assert fuse_motion({}, motion)['measured_type'] == 'unknown'
        assert not plan['curves']


def test_few_distant_inliers_do_not_validate_a_compact_cluster():
    rng = np.random.default_rng(42)
    cluster = rng.uniform(160, 205, (70, 2))
    pts = np.vstack([cluster, [[10, 10], [390, 10], [10, 390], [390, 390]]]).astype(np.float32)
    area, distributed = _spatial_support(pts, pts, np.ones(len(pts)), 400, 400)
    assert area > .85 and not distributed


def test_only_ransac_inliers_contribute_spatial_support():
    local = np.array([(x, y) for x in (80, 90, 100, 110) for y in (80, 90, 100)], dtype=np.float32)
    points = np.vstack([local, [[0, 0], [190, 0], [0, 190], [190, 190]]]).astype(np.float32)
    mask = np.arange(len(points)) < len(local)
    area, distributed = _spatial_support(points, points, mask, 200, 200)
    assert 0 < area < .02 and not distributed



@pytest.mark.parametrize(('layout', 'expected_dx'), [('moving_card', -46), ('static_hud', 69), ('split', None), ('slow_split', None)])
def test_two_plane_camera_and_export(tmp_path, layout, expected_dx):
    # The card is sharper than the background, so a global list of top corners
    # can entirely miss the weaker but well-textured stationary/opposing plane.
    rng = np.random.default_rng(1003)
    background = cv2.resize(rng.integers(83, 174, (90, 210, 3), dtype=np.uint8), (840, 360),
                            interpolation=cv2.INTER_CUBIC)
    foreground = cv2.resize(np.random.default_rng(3871).integers(16, 241, (90, 108, 3), dtype=np.uint8),
                            (432, 360), interpolation=cv2.INTER_CUBIC)
    path = tmp_path / 'layers.mp4'
    with av.open(str(path), 'w') as video:
        stream = video.add_stream('libx264', rate=24)
        stream.width, stream.height, stream.pix_fmt = 640, 360, 'yuv420p'
        stream.options = {'crf': '18', 'threads': '1'}
        for i in range(24):
            offset = 100 - 3*i if layout == 'static_hud' else 100 + 2*i
            if layout == 'slow_split':
                offset = 100
            image = background[:, offset:offset+640].copy()
            if layout == 'moving_card':
                image[53:303, 74+3*i:424+3*i] = foreground[:250, :350]
            elif layout == 'static_hud':
                image[25:97, 405:589] = foreground[:72, :184]
            else:
                step = 1 if layout == 'slow_split' else 3
                image[:, 320:] = foreground[:, 80-step*i:400-step*i]
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, 'bgr24')):
                video.mux(packet)
        for packet in stream.encode():
            video.mux(packet)
    motion = analyze_shot_motion(path, 0, 1, 640, 360)
    shot = {'time': {'start': 0, 'end': 1, 'duration': 1}, 'measured_motion': motion.model_dump()}
    curves = generate_ae_recipe(shot)['animation_plan']['curves']
    if expected_dx is None:
        assert motion.status == 'mixed_support' and motion.mixed_support_pair_count > 0
        assert not curves and fuse_motion({}, motion)['measured_type'] == 'unknown'
    else:
        assert motion.status == 'ok'
        assert motion.translation_x_px == pytest.approx(expected_dx, abs=1)
        assert [c['property'] for c in curves] == ['position_x']
