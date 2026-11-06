"""Compose measured similarities in time order without bridging invalid frame pairs."""
import math

import numpy as np

from schemas.measured_motion import FramePairTransform, MotionSample


def compose_trajectory(pairs: list[FramePairTransform], *, analysis_width: int, analysis_height: int,
                       original_width: int, original_height: int) -> list[MotionSample]:
    if min(analysis_width, analysis_height, original_width, original_height) <= 0:
        raise ValueError('画面尺寸必须为正数')
    to_original = np.diag([original_width / analysis_width, original_height / analysis_height, 1.0])
    to_analysis = np.linalg.inv(to_original)
    center = np.array([original_width / 2, original_height / 2, 1.0])
    samples = []
    composite = np.eye(3)
    segment_id, segment_start, previous_end = -1, None, None
    angle = 0.0

    def append(source_time):
        original = to_original @ composite @ to_analysis
        displacement = original @ center - center
        samples.append(MotionSample(
            source_time=source_time, segment_id=segment_id, segment_start_time=segment_start,
            translation_x_px=float(displacement[0]), translation_y_px=float(displacement[1]),
            translation_x_ratio=float(displacement[0] / original_width),
            translation_y_ratio=float(displacement[1] / original_height),
            scale_ratio=float(math.hypot(composite[0, 0], composite[1, 0])),
            rotation_deg=angle,
            matrix=tuple(tuple(float(value) for value in row) for row in original[:2]),
        ))

    for pair in pairs:
        if not pair.valid:
            previous_end = None
            continue
        if pair.start_time is None or pair.end_time is None or pair.end_time <= pair.start_time:
            raise ValueError('有效帧对必须包含递增的实际时间')
        if samples and pair.start_time < samples[-1].source_time:
            raise ValueError('帧对时间不能倒退')
        if previous_end != pair.start_time:
            segment_id += 1
            segment_start = pair.start_time
            composite, angle = np.eye(3), 0.0
            append(pair.start_time)
        radians = math.radians(pair.rotation_deg)
        a, b = pair.scale_ratio * math.cos(radians), pair.scale_ratio * math.sin(radians)
        step = np.array([[a, -b, pair.dx_px], [b, a, pair.dy_px], [0, 0, 1]])
        composite = step @ composite
        # Keep accumulated rotation unwrapped, including rotations beyond 180 degrees.
        angle += pair.rotation_deg
        append(pair.end_time)
        previous_end = pair.end_time
    return samples
