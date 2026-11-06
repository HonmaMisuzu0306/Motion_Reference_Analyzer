from math import cos, radians, sin

import av
import cv2
import numpy as np
import pytest

from cv.region_track import NormalizedBox, RegionSample, RegionTrack, track_region
from cv.two_pin import derive_two_pin, minimum_baseline_px

W, H = 448, 320
A, V = np.array([208.0, 161.0]), np.array([83.0, -32.0])


def rotate(angle):
    c, s = cos(radians(angle)), sin(radians(angle))
    return np.array([[c, -s], [s, c]])


def box(p, width=W, height=H):
    return NormalizedBox(x=float((p[0] - 9) / width), y=float((p[1] - 9) / height),
                         width=18 / width, height=18 / height)


def raw(centers, times, **kwargs):
    return RegionTrack(status=kwargs.pop('status', 'complete'), frame_width=W, frame_height=H,
                       samples=[RegionSample(source_time=t, center_x_px=float(p[0]), center_y_px=float(p[1]))
                                for t, p in zip(times, centers, strict=True)], **kwargs)


def test_vfr_source_clock_off_axis_pivot_scale_and_continuous_turn():
    times = [9.42, 9.50, 9.71, 9.95, 10.22, 10.41, 10.51, 10.68]
    angles = [0, -31, -65, -103, -141, -187, -229, -241]
    scales = [1, .96, 1.04, 1.15, 1.19, 1.08, 1.05, .90]
    left = [A + [i * 1.5, i * .4] for i in range(len(times))]
    right = [p + rotate(angle) @ V * scale for p, angle, scale in zip(left, angles, scales)]
    pose = derive_two_pin(raw(left, times), raw(right, times), box(A), box(A + V))
    assert pose.status == 'complete' and pose.stop_time is None
    assert (pose.initial_vector_x_px, pose.initial_vector_y_px) == tuple(V)
    assert pose.initial_distance_px == pytest.approx(np.linalg.norm(V))
    for row, pos, other, angle, scale, t in zip(pose.samples, left, right, angles, scales, times, strict=True):
        assert row.source_time == t
        assert [row.position_x_px, row.position_y_px] == pytest.approx(pos)
        assert [row.pin_b_x_px, row.pin_b_y_px] == pytest.approx(other)
        assert row.rotation_deg == pytest.approx(angle)
        assert row.scale_percent == pytest.approx(scale * 100)


def test_does_not_resynchronize_or_publish_after_missing_pin():
    left = raw([A] * 4, [5, 5.125, 5.25, 5.375])
    right = raw([A + V] * 3, [5, 5.25, 5.375])
    pose = derive_two_pin(left, right, box(A), box(A + V))
    assert (pose.status, pose.stop_time) == ('time_mismatch', 5.125)
    assert [r.source_time for r in pose.samples] == [5]
    right = raw([A + V] * 2, [5, 5.125], status='ambiguous', stop_time=5.25)
    pose = derive_two_pin(left, right, box(A), box(A + V))
    assert (pose.status, pose.stop_time, pose.pin_b_status) == ('pin_lost', 5.25, 'ambiguous')
    assert [r.source_time for r in pose.samples] == [5, 5.125]
    # The shorter complete list stops matching before the longer pin's later loss.
    short = raw([A], [5])
    pose = derive_two_pin(short, right, box(A), box(A + V))
    assert (pose.status, pose.stop_time) == ('time_mismatch', 5.125)


def test_mismatched_frame_geometry_anchor_or_box_has_no_pose():
    aa, bb = raw([A], [1]), raw([A + V], [1])
    checks = [(aa, bb, box(A), box(A + [1, 0]), 'overlapping_boxes'),
              (aa, bb, box(A + [1, 0]), box(A + V), 'anchor_mismatch'),
              (aa, raw([A + V], [1.001]), box(A), box(A + V), 'anchor_mismatch'),
              (aa, bb.model_copy(update={'frame_width': 800}), box(A), box(A + V), 'geometry_changed'),
              (aa, raw([], [], status='insufficient_texture', stop_time=1), box(A), box(A + V), 'no_samples')]
    for a, b, a_box, b_box, reason in checks:
        pose = derive_two_pin(a, b, a_box, b_box)
        assert pose.status == reason and not pose.samples and pose.initial_distance_px is None


@pytest.mark.parametrize(('d0', 'd1', 'degrees', 'times', 'reason'), [
    (30, 55, 0, [0, .125], 'baseline_too_short'), (83, 30, 0, [0, .125], 'degenerate'),
    (83, 83, 115, [0, .125], 'angle_jump'), (83, 83, 0, [0, .65], 'time_gap'),
])
def test_geometrical_and_temporal_stops_remove_first_ambiguous_pose(d0, d1, degrees, times, reason):
    aa = raw([A, A], times)
    bb = raw([A + [d0, 0], A + rotate(degrees) @ np.array([d1, 0])], times)
    pose = derive_two_pin(aa, bb, box(A), box(A + [d0, 0]))
    expected = 0 if reason == 'baseline_too_short' else 1
    assert pose.status == reason and len(pose.samples) == expected and pose.stop_time == times[expected]
    assert minimum_baseline_px(3840, 2160) == pytest.approx(50 * 3840 / 720)


def test_malformed_input_never_becomes_a_pose():
    track = raw([A, A], [2, 2])
    with pytest.raises(ValueError):
        derive_two_pin(track, raw([A + V], [2]), box(A), box(A + V))
    with pytest.raises(ValueError):
        derive_two_pin(raw([A], [2]), raw([[float('nan'), 2]], [2]), box(A), box(A + V))


def test_two_real_tracks_yield_correct_combined_pose_until_one_marker_is_covered(tmp_path):
    # The artwork layer is transformed as one image. Coded points and expected
    # values are independent of optical flow, template matching and fusion.
    file = tmp_path / 'two-markers.mp4'
    w, h = 192, 144
    axis = np.array([68., 44.])
    baseline = np.array([65., 18.])
    plate = np.full((h, w), 45, np.uint8)
    for cx, cy in (axis, axis + baseline):
        xy = (int(cx), int(cy))
        cv2.circle(plate, xy, 7, 190, -1)
        cv2.circle(plate, xy, 4, 30, -1)
        cv2.circle(plate, xy, 2, 250, -1)
    with av.open(str(file), 'w') as out:
        stream = out.add_stream('libx264', rate=24)
        stream.width, stream.height, stream.pix_fmt = w, h, 'yuv420p'
        for i in range(24):
            linear = rotate(i * .85) * (1 + i * .002)
            dest = axis + [i * .5, -i * .25]
            frame = cv2.warpAffine(plate, np.column_stack([linear, dest - linear @ axis]),
                                   (w, h), borderMode=cv2.BORDER_REPLICATE)
            if i >= 18:
                x, y = np.rint(dest + linear @ baseline).astype(int)
                frame[y-12:y+13, x-12:x+13] = 45
            for packet in stream.encode(av.VideoFrame.from_ndarray(frame, format='gray')):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    a_box, b_box = box(axis, w, h), box(axis + baseline, w, h)
    a, b = [track_region(file, 0, 1, 0, pin) for pin in (a_box, b_box)]
    pose = derive_two_pin(a, b, a_box, b_box)
    assert (pose.status, pose.stop_time) == ('pin_lost', .75)
    assert [s.source_time for s in pose.samples] == [i/24 for i in range(0, 18, 3)]
    for s in pose.samples:
        i = round(24 * s.source_time)
        assert [s.position_x_px, s.position_y_px] == pytest.approx(axis + [i*.5, -i*.25], abs=.25)
        assert s.rotation_deg == pytest.approx(i*.85, abs=.4)
        assert s.scale_percent == pytest.approx(100 + i*.2, abs=.55)
