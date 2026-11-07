"""Follow the visible pattern in a user-selected box, in upright display coordinates."""

from contextlib import closing
from math import hypot, isclose, isfinite
from pathlib import Path
from typing import BinaryIO, Literal, Self

import cv2
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cv.frame_sampler import iter_frames_for_cv

MAX_DURATION = 30.0
SAMPLE_FPS = 8
MAX_SAMPLES = int(MAX_DURATION * SAMPLE_FPS) + 2
MAX_SOURCE_PIXELS = 4096 * 2304
MAX_DECODED_FRAMES = 4096  # includes pre-roll from the preceding keyframe
MIN_SIDE = 12
SEARCH_RADIUS = 56


class NormalizedBox(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid', frozen=True, strict=True)
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode='after')
    def check_bounds(self) -> Self:
        if self.x + self.width > 1 + 1e-12 or self.y + self.height > 1 + 1e-12:
            raise ValueError('初始框必须完全位于显示画幅内')
        return self


class RegionSample(BaseModel):
    source_time: float
    center_x_px: float
    center_y_px: float


RegionStatus = Literal[
    'complete', 'no_frames', 'anchor_mismatch', 'box_too_small',
    'insufficient_texture', 'no_match', 'ambiguous', 'abrupt_change',
    'geometry_changed', 'time_gap',
]


class RegionTrack(BaseModel):
    status: RegionStatus
    stop_time: float | None = None
    frame_width: int = 0
    frame_height: int = 0
    samples: list[RegionSample] = Field(default_factory=list)


def _peak_offset(left, middle, right):
    denominator = float(left) + float(right) - 2 * float(middle)
    if denominator >= -1e-7:
        return 0.0
    return max(-0.5, min(0.5, 0.5 * (float(left) - float(right)) / denominator))


def _find_match(gray, template, previous):
    height, width = template.shape
    last_x, last_y = map(round, previous)
    x0, y0 = max(0, last_x - SEARCH_RADIUS), max(0, last_y - SEARCH_RADIUS)
    crop = gray[y0:last_y + SEARCH_RADIUS + height, x0:last_x + SEARCH_RADIUS + width]
    scores = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    # A box spanning an entire axis has no competing positions on that axis.
    # A high score alone cannot establish that the centre stayed in place.
    if min(scores.shape) < 9:
        return 'ambiguous', previous
    _, peak, _, (x, y) = cv2.minMaxLoc(scores)
    if peak < 0.78:
        return 'no_match', previous
    dx = _peak_offset(*scores[y, x-1:x+2]) if 0 < x < scores.shape[1]-1 else 0
    dy = _peak_offset(*scores[y-1:y+2, x]) if 0 < y < scores.shape[0]-1 else 0
    # Suppress the immediate peak and require a clear lead over separate matches.
    scores[max(0, y-4):y+5, max(0, x-4):x+5] = -1
    if peak - float(scores.max()) < 0.08:
        return 'ambiguous', previous
    return 'complete', (x0 + x + dx, y0 + y + dy)


def track_region(
    source: str | Path | BinaryIO,
    start_time: float,
    end_time: float,
    anchor_time: float,
    box: NormalizedBox,
) -> RegionTrack:
    """Track from the box's exact source-relative anchor PTS to exclusive end_time.

    Invalid requests, unsupported video geometry and resource limits raise ValueError.
    Loss of visual evidence returns the confirmed prefix with its first rejected PTS.
    """
    if not all(isfinite(t) for t in (start_time, end_time, anchor_time)):
        raise ValueError('时间范围与首帧时间必须为有限数值')
    if not 0 <= start_time <= anchor_time < end_time or end_time - start_time > MAX_DURATION:
        raise ValueError('时间范围需包含首帧，最长为 30 秒')
    box = NormalizedBox.model_validate(box)
    result = RegionTrack(status='no_frames')
    template = None
    frames = iter_frames_for_cv(
        source, anchor_time, end_time, target_fps=SAMPLE_FPS,
        max_decoded_frames=MAX_DECODED_FRAMES, max_source_pixels=MAX_SOURCE_PIXELS,
    )
    with closing(frames):
        for frame in frames:
            time = frame['timestamp']
            original = frame['original_width'], frame['original_height']
            gray = cv2.cvtColor(frame['image'], cv2.COLOR_BGR2GRAY)
            height, width = gray.shape
            if template is None:
                result.frame_width, result.frame_height = original
                if not isclose(time, anchor_time, abs_tol=1e-9, rel_tol=0):
                    result.status, result.stop_time = 'anchor_mismatch', time
                    break
                initial = round(box.x * width), round(box.y * height)
                right = round((box.x + box.width) * width)
                bottom = round((box.y + box.height) * height)
                template = gray[initial[1]:bottom, initial[0]:right].copy()
                if min(template.shape) < MIN_SIDE:
                    result.status, result.stop_time = 'box_too_small', time
                    break
                if template.std() < 8:
                    result.status, result.stop_time = 'insufficient_texture', time
                    break
                # Keep the exact centre selected by the user even when the analysis
                # raster rounds the crop boundaries to neighbouring pixels.
                anchor_x = (box.x + box.width / 2) * original[0]
                anchor_y = (box.y + box.height / 2) * original[1]
                scale_x, scale_y = original[0] / width, original[1] / height
                previous = initial
                result.status = 'complete'
            else:
                if original != (result.frame_width, result.frame_height):
                    result.status, result.stop_time = 'geometry_changed', time
                    break
                if time - result.samples[-1].source_time > 0.5:
                    result.status, result.stop_time = 'time_gap', time
                    break
                status, position = _find_match(gray, template, previous)
                if status != 'complete':
                    result.status, result.stop_time = status, time
                    break
                if len(result.samples) >= 2:
                    old, latest = result.samples[-2:]
                    dt = (time - latest.source_time) / (latest.source_time - old.source_time)
                    expected_dx = (latest.center_x_px - old.center_x_px) * dt / scale_x
                    expected_dy = (latest.center_y_px - old.center_y_px) * dt / scale_y
                    error = hypot(position[0] - previous[0] - expected_dx,
                                  position[1] - previous[1] - expected_dy)
                    if error > max(8, min(template.shape) / 2):
                        result.status, result.stop_time = 'abrupt_change', time
                        break
                previous = position
            if len(result.samples) >= MAX_SAMPLES:
                raise ValueError('跟踪样本数超出预算，请缩短时间范围')
            result.samples.append(RegionSample(
                source_time=time,
                center_x_px=anchor_x + (previous[0] - initial[0]) * scale_x,
                center_y_px=anchor_y + (previous[1] - initial[1]) * scale_y,
            ))
    return result
