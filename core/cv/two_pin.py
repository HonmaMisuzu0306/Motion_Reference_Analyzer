"""A two-point similarity under the user's explicit same-layer assumption."""
from math import atan2, degrees, hypot, isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cv.frame_sampler import CV_ANALYSIS_MAX_LONG_EDGE
from cv.region_track import MAX_SAMPLES, NormalizedBox, RegionStatus, RegionTrack

# Opposing 0.5 px pin errors can change length by 1 px, or 2% at 50 px.
# This is a conditioning guard, not a confidence estimate for the observations.
MIN_BASELINE_ANALYSIS_PX = 50
MAX_STEP_DEGREES = 60.0

TwoPinStatus = Literal[
    'complete', 'pin_lost', 'no_samples', 'overlapping_boxes', 'geometry_changed',
    'anchor_mismatch', 'time_mismatch', 'time_gap', 'baseline_too_short', 'degenerate', 'angle_jump',
]


class TwoPinSample(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    source_time: float
    position_x_px: float
    position_y_px: float
    rotation_deg: float
    scale_percent: float
    pin_b_x_px: float
    pin_b_y_px: float


class TwoPinTrack(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    status: TwoPinStatus
    stop_time: float | None = None
    frame_width: int = 0
    frame_height: int = 0
    initial_vector_x_px: float | None = None
    initial_vector_y_px: float | None = None
    initial_distance_px: float | None = None
    pin_a_status: RegionStatus
    pin_b_status: RegionStatus
    samples: list[TwoPinSample] = Field(default_factory=list)


def _overlap(a, b):
    intersection_w = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    intersection_h = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    return min(intersection_w, intersection_h) > 1e-12


def minimum_baseline_px(width: int, height: int) -> float:
    """Translate the estimator's pixel floor back to full upright display pixels."""
    if min(width, height) <= 0:
        raise ValueError('无效的显示画幅')
    factor = min(1.0, CV_ANALYSIS_MAX_LONG_EDGE / max(width, height))
    analysis_w, analysis_h = max(1, int(width * factor)), max(1, int(height * factor))
    return MIN_BASELINE_ANALYSIS_PX * max(width / analysis_w, height / analysis_h)


def _validate(track):
    if min(track.frame_width, track.frame_height) < 0:
        raise ValueError('位置轨迹包含无效显示画幅')
    if len(track.samples) > MAX_SAMPLES:
        raise ValueError('位置轨迹超过采样上限')
    last = -1.0
    for point in track.samples:
        if (not isfinite(point.source_time) or point.source_time <= last or point.source_time < 0
                or not 0 <= point.center_x_px < track.frame_width
                or not 0 <= point.center_y_px < track.frame_height):
            raise ValueError('位置轨迹包含无效时间或显示坐标')
        last = point.source_time
    stop = track.stop_time
    if stop is not None and (not isfinite(stop) or stop < 0 or stop <= last or track.status == 'complete'):
        raise ValueError('位置轨迹的停止时间无效')
    if track.samples and track.status != 'complete' and stop is None:
        raise ValueError('位置轨迹缺少停止时间')


def derive_two_pin(a: RegionTrack, b: RegionTrack, box_a: NormalizedBox, box_b: NormalizedBox) -> TwoPinTrack:
    """Fuse tracks from the same verified source and anchor, without filling either track.

    Positive angles turn clockwise in upright display pixels. Two observations alone
    cannot identify layers. The caller must bind the source and the user's two boxes.
    """
    _validate(a)
    _validate(b)
    width, height = a.frame_width, a.frame_height
    result = TwoPinTrack(status='complete', frame_width=width, frame_height=height,
                         pin_a_status=a.status, pin_b_status=b.status)

    def stop(reason, time=None):
        result.status, result.stop_time = reason, time
        return result

    if _overlap(box_a, box_b):
        return stop('overlapping_boxes')
    if not a.samples or not b.samples:
        missing_times = [track.stop_time for track in (a, b) if not track.samples and track.stop_time is not None]
        return stop('no_samples', min(missing_times, default=None))
    if (width, height) != (b.frame_width, b.frame_height):
        return stop('geometry_changed')
    if a.samples[0].source_time != b.samples[0].source_time:
        return stop('anchor_mismatch', min(a.samples[0].source_time, b.samples[0].source_time))
    for track, box in ((a, box_a), (b, box_b)):
        anchor = track.samples[0]
        x, y = (box.x + box.width / 2) * width, (box.y + box.height / 2) * height
        if hypot(anchor.center_x_px - x, anchor.center_y_px - y) > 1e-6:
            return stop('anchor_mismatch', anchor.source_time)

    min_distance = minimum_baseline_px(width, height)
    rotation = 0.0
    prev_dx, prev_dy = 0.0, 0.0
    for left, right in zip(a.samples, b.samples):
        t = left.source_time
        if t != right.source_time:
            return stop('time_mismatch', min(t, right.source_time))
        if result.samples and t - result.samples[-1].source_time > .5:
            return stop('time_gap', t)
        dx, dy = right.center_x_px - left.center_x_px, right.center_y_px - left.center_y_px
        length = hypot(dx, dy)
        if length < min_distance:
            return stop('degenerate' if result.samples else 'baseline_too_short', t)
        if not result.samples:
            result.initial_vector_x_px, result.initial_vector_y_px = dx, dy
            result.initial_distance_px = length
        else:
            # atan2(cross, dot) is the signed shortest increment, even at the +/-180 seam.
            turn = degrees(atan2(prev_dx * dy - prev_dy * dx, prev_dx * dx + prev_dy * dy))
            if abs(turn) > MAX_STEP_DEGREES + 1e-9:
                return stop('angle_jump', t)
            rotation += turn
        result.samples.append(TwoPinSample(
            source_time=t, position_x_px=left.center_x_px, position_y_px=left.center_y_px,
            pin_b_x_px=right.center_x_px, pin_b_y_px=right.center_y_px,
            rotation_deg=rotation, scale_percent=100.0 * (length / result.initial_distance_px),
        ))
        prev_dx, prev_dy = dx, dy

    count = len(result.samples)
    unmatched = [track.samples[count].source_time for track in (a, b) if len(track.samples) > count]
    cutoffs = [track.stop_time for track in (a, b) if track.stop_time is not None]
    first_loss = min(cutoffs, default=float('inf'))
    first_unmatched = min(unmatched, default=float('inf'))
    if first_unmatched < first_loss:
        return stop('time_mismatch', first_unmatched)
    if cutoffs:
        return stop('pin_lost', first_loss)
    return result
