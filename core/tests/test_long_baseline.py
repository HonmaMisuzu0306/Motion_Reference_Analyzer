import numpy as np
import pytest

from cv import long_baseline
from cv.long_baseline import LongBaselineCheck


def feed(check, times, *, invalid_at=(), dx=1):
    image = np.full((24, 32, 3), 20, dtype=np.uint8)
    for a, b in zip(times, times[1:]):
        check.observe({'timestamp': a, 'image': image}, {'timestamp': b, 'image': image},
                      {'valid': b not in invalid_at, 'support_area_ratio': .75,
                       'dx_px': dx, 'dy_px': 0., 'rotation_deg': 0., 'scale_ratio': 1.})


@pytest.mark.parametrize('outcomes,expected', [
    ([False], 0), ([True, False], 0), ([True], 2),
])
def test_mixed_evidence_must_repeat_across_directions_and_disjoint_spans(monkeypatch, outcomes, expected):
    from itertools import cycle

    answers = cycle(outcomes)
    monkeypatch.setattr(long_baseline, 'estimate_transform_between_grays',
                        lambda *_: {'mixed_support': next(answers)})
    check = LongBaselineCheck(12, 16, 8)
    feed(check, np.arange(12, 16, .125))
    assert check.conflict_count == expected
    assert check.check_count == (2 if expected else 4)


def test_does_not_bridge_missing_frames_or_a_tracking_gap(monkeypatch):
    def unexpected(*_):
        pytest.fail('unexpected long match')

    monkeypatch.setattr(long_baseline, 'estimate_transform_between_grays', unexpected)
    check = LongBaselineCheck(0, 2, 8)
    feed(check, [0, .125, .25, .375, .5, .625, .75, 1, 1.125, 1.625, 1.75, 1.875],
         invalid_at=[.375])
    assert check.check_count == 0


def test_fast_and_short_moves_are_not_long_distance_evidence(monkeypatch):
    monkeypatch.setattr(long_baseline, 'estimate_transform_between_grays', lambda *_: pytest.fail())
    check = LongBaselineCheck(0, 4, 8)
    feed(check, np.arange(0, 4, .125), dx=6)
    assert check.check_count == 0
    short = LongBaselineCheck(0, 1, 8)
    feed(short, np.arange(0, 1, .125))
    assert short.check_count == 0


def write_slow_layers(path, *, hud):
    import av
    import cv2

    width, height = 480, 288
    rng = np.random.default_rng(11052026)
    background, moving = [
        cv2.resize(rng.integers(16, 240, (height//2, width//2, 3), dtype=np.uint8),
                   (2*width, 2*height), interpolation=cv2.INTER_CUBIC) for _ in range(2)
    ]
    fixed = background[height//2:height//2+height, width//2:width//2+width].copy()
    with av.open(str(path), 'w') as out:
        video = out.add_stream('libx264', rate=24)
        video.width, video.height, video.pix_fmt = width, height, 'yuv420p'
        video.options = {'threads': '1', 'crf': '19', 'preset': 'veryfast'}
        for idx in range(96):
            affine = np.float32([[1, 0, -width/2 + idx/4], [0, 1, -height/2]])
            if hud:
                affine[1, 2] -= idx/8
                image = cv2.warpAffine(background, affine, (width, height))
                image[14:48, 350:465] = moving[:34, :115]
            else:
                right = cv2.warpAffine(moving, affine, (width, height))
                fixed[:, width//2:] = right[:, width//2:]
                image = fixed
            for packet in video.encode(av.VideoFrame.from_ndarray(image, 'bgr24')):
                out.mux(packet)
        for packet in video.encode():
            out.mux(packet)

    return width, height


def test_encoded_subpixel_split_vetoes_adjacent_affine_solution(tmp_path):
    from cv.motion_analyzer import analyze_shot_motion
    from recipe.ae_recipe import generate_ae_recipe

    path = tmp_path / 'slow-split.mp4'
    width, height = write_slow_layers(path, hud=False)
    motion = analyze_shot_motion(path, 0, 4, width, height)
    assert motion.status == 'mixed_support' and motion.long_baseline_conflict_count >= 2
    assert motion.valid_pair_count == motion.total_pair_count and not motion.mixed_support_pair_count
    assert motion.trajectory == []
    plan = generate_ae_recipe({'time': {'start': 0, 'end': 4},
                               'measured_motion': motion.model_dump()})['animation_plan']
    assert not plan['curves']


def test_stationary_hud_does_not_add_scale_to_slow_camera_pan(tmp_path):
    from cv.motion_analyzer import analyze_shot_motion
    from recipe.ae_recipe import generate_ae_recipe

    path = tmp_path / 'pan-with-hud.mp4'
    width, height = write_slow_layers(path, hud=True)
    motion = analyze_shot_motion(path, 0, 4, width, height)
    assert motion.status == 'ok'
    assert motion.translation_x_px == pytest.approx(95/4, abs=.5)
    assert motion.translation_y_px == pytest.approx(-95/8, abs=.5)
    plan = generate_ae_recipe({'time': {'start': 0, 'end': 4},
                               'measured_motion': motion.model_dump()})['animation_plan']
    assert {c['property'] for c in plan['curves']} == {'position_x', 'position_y'}
