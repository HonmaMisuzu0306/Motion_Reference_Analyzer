"""Use a few longer spans to cross-check apparently smooth, slow global motion."""
from math import cos, hypot, radians, sin

import cv2

from cv.transform import estimate_transform_between_grays

_WINDOW_SECONDS = 0.75
_MAX_WINDOWS = 6


class LongBaselineCheck:
    """At most one forward/reverse check per slot, retaining one gray anchor.

    A lone discrepancy, failed tracking, or unrelated frames do not establish
    competing motion. Only repeated *positive* conflict evidence can veto a
    complete adjacent-pair path. All reported pair counts keep their semantics.
    """

    def __init__(self, start, end, fps):
        self.start = start
        self.enabled = end - start >= 2
        self.period = max(1.0, (end - start) / _MAX_WINDOWS)
        self.gap_limit = min(.32, 1.75 / fps) if fps > 0 else 0
        self.slot = -1
        self.anchor = None
        self.check_count = 0
        self.conflict_count = 0

    def observe(self, previous, current, result):
        if not self.enabled or self.conflict_count >= 2:
            return
        t0, t1 = previous['timestamp'], current['timestamp']
        slot = int((t0 - self.start) / self.period)
        if not 0 <= slot < _MAX_WINDOWS:
            return
        continuous = (0 < t1 - t0 <= self.gap_limit and result['valid']
                      and result.get('support_area_ratio') is not None)
        if slot != self.slot:
            self.slot = slot
            self.anchor = cv2.cvtColor(previous['image'], cv2.COLOR_BGR2GRAY) if continuous else None
            self.anchor_time = t0
            self.travel = 0.
            self.count = 0
        if not continuous:
            self.anchor = None
        if self.anchor is None:
            return

        # Upper bound on the displacement of any pixel by this short transform.
        # Long-distance LK with large shifts or scale/rotation is unreliable.
        angle = radians(result['rotation_deg'])
        scale = result['scale_ratio']
        linear_change = hypot(scale * cos(angle) - 1, scale * sin(angle))
        self.travel += hypot(result['dx_px'], result['dy_px']) + hypot(*self.anchor.shape) * linear_change
        self.count += 1
        if self.travel > 20:
            self.anchor = None
            return
        if t1 - self.anchor_time < _WINDOW_SECONDS:
            return
        anchor, self.anchor = self.anchor, None
        if self.count < 3 or self.travel < .5:
            return
        gray = cv2.cvtColor(current['image'], cv2.COLOR_BGR2GRAY)
        self.check_count += 1
        if (estimate_transform_between_grays(anchor, gray).get('mixed_support')
                and estimate_transform_between_grays(gray, anchor).get('mixed_support')):
            self.conflict_count += 1
