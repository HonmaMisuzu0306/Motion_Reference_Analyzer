"""Bounded, shared hard-cut detection with motion and single-frame flash evidence."""
from dataclasses import dataclass
from functools import cached_property
from math import isfinite

import cv2
import numpy as np

SCENE_DETECT_VERSION = 'spatial-affine-v4'
SCENE_CUT_THRESHOLD = 25.0
MOTION_SIZE = 64
_WINDOW = cv2.createHanningWindow((MOTION_SIZE, MOTION_SIZE), cv2.CV_32F)
_PROBES = np.array([[12, 12], [52, 12], [12, 52], [52, 52], [32, 32]], np.float32)


def frame_signature(frame: np.ndarray, bins: int = 16) -> np.ndarray:
    """Keep the layout of area-averaged BGR cells, including for tiny source frames."""
    return cv2.resize(frame, (bins, bins), interpolation=cv2.INTER_AREA).astype(np.float32)


def scene_change_score(previous: np.ndarray, current: np.ndarray) -> float:
    # Average magnitudes, not signed differences: swapped regions must not cancel out.
    return float(np.linalg.norm(current - previous, axis=2).mean())


@dataclass(frozen=True)
class _Frame:
    time: float
    signature: np.ndarray
    rgb: np.ndarray

    @cached_property
    def gray(self) -> np.ndarray:
        return cv2.cvtColor(self.rgb, cv2.COLOR_BGR2GRAY)

    @cached_property
    def color(self) -> np.ndarray:
        return self.rgb.mean(axis=(0, 1))

    @cached_property
    def contrast(self) -> float:
        return float(np.linalg.norm(self.rgb - self.color, axis=2).mean())


@dataclass(frozen=True)
class _Motion:
    displacement: np.ndarray
    elapsed: float


def _describe(time: float, image: np.ndarray) -> _Frame:
    if not isfinite(time):
        raise ValueError('帧时间必须为有限值')
    rgb = cv2.resize(image, (MOTION_SIZE, MOTION_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
    return _Frame(time, frame_signature(image), rgb)


def _translation(previous: _Frame, current: _Frame) -> _Motion | None:
    """Accept only textured, well-overlapped small translations with low RGB residual.

    Phase correlation proposes the shift; the color residual verifies it. This is
    intentionally bounded to avoid matching unrelated half-frame/layout swaps.
    """
    if previous.gray.std() < 5 or current.gray.std() < 5:
        return None
    shift, response = cv2.phaseCorrelate(
        previous.gray - previous.gray.mean(), current.gray - current.gray.mean(), _WINDOW)
    dx, dy = shift
    if not all(isfinite(value) for value in (dx, dy, response)) or response < .6:
        return None
    if max(abs(dx), abs(dy)) > MOTION_SIZE * .2:
        return None
    overlap = (1 - abs(dx) / MOTION_SIZE) * (1 - abs(dy) / MOTION_SIZE)
    if overlap < .75:
        return None
    matrix = np.array([[1, 0, -dx], [0, 1, -dy]], np.float32)
    aligned = cv2.warpAffine(current.rgb, matrix, (MOTION_SIZE, MOTION_SIZE))
    valid = cv2.warpAffine(np.ones((MOTION_SIZE, MOTION_SIZE), np.float32), matrix,
                           (MOTION_SIZE, MOTION_SIZE)) > .999
    valid[:2] = valid[-2:] = False
    valid[:, :2] = valid[:, -2:] = False
    residual = float(np.linalg.norm(previous.rgb - aligned, axis=2)[valid].mean())
    if residual > 18:
        return None
    return _Motion(np.tile([dx, dy], (len(_PROBES), 1)), current.time - previous.time)


def _affine(previous: _Frame, current: _Frame) -> _Motion | None:
    """Verify a bounded global warp with distributed tracks and RGB agreement.

    Full affine coordinates compensate for the non-square source being resized
    to a square descriptor. Forward/backward tracks and spatial support prevent
    a small moving object from explaining an unrelated whole-frame change.
    """
    a, b = previous.gray.astype(np.uint8), current.gray.astype(np.uint8)
    points = cv2.goodFeaturesToTrack(a, 100, .01, 4, blockSize=3)
    if points is None or len(points) < 12:
        return None
    moved, status, _ = cv2.calcOpticalFlowPyrLK(a, b, points, None, winSize=(15, 15), maxLevel=2)
    if moved is None:
        return None
    returned, back_status, _ = cv2.calcOpticalFlowPyrLK(b, a, moved, None, winSize=(15, 15), maxLevel=2)
    if returned is None:
        return None
    good = ((status.ravel() == 1) & (back_status.ravel() == 1)
            & (np.linalg.norm(returned - points, axis=2).ravel() < .8))
    source, target = points.reshape(-1, 2)[good], moved.reshape(-1, 2)[good]
    if len(source) < 12 or len(source) < .6 * len(points):
        return None
    matrix, inliers = cv2.estimateAffine2D(source, target, method=cv2.RANSAC,
                                         ransacReprojThreshold=.75, maxIters=300)
    if matrix is None or not np.isfinite(matrix).all() or inliers.mean() < .8:
        return None
    supported = source[inliers.ravel().astype(bool)]
    if cv2.contourArea(cv2.convexHull(supported)) < .3 * MOTION_SIZE ** 2:
        return None
    singular = np.linalg.svd(matrix[:, :2], compute_uv=False)
    if np.linalg.det(matrix[:, :2]) <= 0 or singular.min() < .8 or singular.max() > 1.25:
        return None
    displacement = _PROBES @ matrix[:, :2].T + matrix[:, 2] - _PROBES
    if np.linalg.norm(displacement, axis=1).max() > .2 * MOTION_SIZE:
        return None
    inverse = cv2.invertAffineTransform(matrix)
    aligned = cv2.warpAffine(current.rgb, inverse, (MOTION_SIZE, MOTION_SIZE))
    valid = cv2.warpAffine(np.ones_like(current.gray), inverse, (MOTION_SIZE, MOTION_SIZE)) > .999
    valid[:2] = valid[-2:] = False
    valid[:, :2] = valid[:, -2:] = False
    if valid.mean() < .7:
        return None
    residual = float(np.linalg.norm(previous.rgb - aligned, axis=2)[valid].mean())
    if residual > 25:
        return None
    return _Motion(displacement, current.time - previous.time)


def _motion(previous: _Frame, current: _Frame) -> _Motion | None:
    return _affine(previous, current) or _translation(previous, current)


def _consistent(first: _Motion | None, second: _Motion | None) -> bool:
    if first is None or second is None:
        return False
    # A static neighbor does not explain an isolated crop/jump cut as continuous pan.
    first_size = float(np.linalg.norm(first.displacement, axis=1).mean())
    second_size = float(np.linalg.norm(second.displacement, axis=1).mean())
    if min(first_size, second_size) < .2:
        return False
    # Compare velocities over the shorter observed interval, preserving VFR timing.
    interval = min(first.elapsed, second.elapsed)
    a = first.displacement * interval / first.elapsed
    b = second.displacement * interval / second.elapsed
    difference = float(np.linalg.norm(a - b, axis=1).max())
    magnitude = max(float(np.linalg.norm(a, axis=1).max()), float(np.linalg.norm(b, axis=1).max()))
    return difference <= .5 + .3 * magnitude


@dataclass(frozen=True)
class _Pair:
    before: _Frame
    current: _Frame

    @cached_property
    def score(self) -> float:
        return scene_change_score(self.before.signature, self.current.signature)

    @cached_property
    def motion(self) -> _Motion | None:
        return _motion(self.before, self.current)


def _flash_color(before: _Frame, current: _Frame, after: _Frame, threshold: float) -> bool:
    if current.contrast > max(8.0, .25 * min(before.contrast, after.contrast)):
        return False
    # A near-uniform extreme outside both neighboring color ranges is flash-like.
    low, high = np.minimum(before.color, after.color), np.maximum(before.color, after.color)
    outside = np.maximum(np.maximum(low - current.color, current.color - high), 0)
    return bool(np.linalg.norm(outside) > threshold)


class SceneBoundaryDetector:
    """One-frame lookahead; retains at most three 64px descriptors between calls.

    For A -> flash -> A, publish no cut. For A -> flash -> B, publish one cut
    at the flash PTS (first observed change), not B's later PTS. Only provided
    frames are examined, so callers can enforce a strict half-open selection.
    """

    def __init__(self, threshold: float = SCENE_CUT_THRESHOLD):
        if not isfinite(threshold) or threshold < 0:
            raise ValueError('切镜阈值必须为非负有限值')
        self.threshold = threshold
        self._latest: _Frame | None = None
        self._previous: _Pair | None = None
        self._pending: _Pair | None = None
        self._skip_next_boundary = False
        self._finished = False

    def push(self, time: float, image: np.ndarray) -> list[float]:
        if self._finished:
            raise ValueError('判定器已结束')
        frame = _describe(time, image)
        if self._latest is not None and time <= self._latest.time:
            raise ValueError('帧时间必须严格递增')
        following = _Pair(self._latest, frame) if self._latest is not None else None
        cuts = self._decide(following)
        self._previous, self._pending = self._pending, following
        self._latest = frame
        return cuts

    def _decide(self, following: _Pair | None) -> list[float]:
        if self._skip_next_boundary:
            self._skip_next_boundary = False
            return []
        pair = self._pending
        if pair is None or pair.score <= self.threshold:
            return []
        before, current = pair.before, pair.current
        if following is not None and following.score > self.threshold:
            after = following.current
            if _flash_color(before, current, after, self.threshold):
                self._skip_next_boundary = True
                if (scene_change_score(before.signature, after.signature) <= self.threshold
                        or _motion(before, after) is not None):
                    return []
                return [current.time]

        # A low-score neighbor can confirm continuous motion. Estimate it only
        # when this candidate has a usable transform, then retain it for reuse.
        if pair.motion is not None:
            if self._previous is not None and _consistent(self._previous.motion, pair.motion):
                return []
            if following is not None and _consistent(pair.motion, following.motion):
                return []
        return [current.time]

    def finish(self) -> list[float]:
        if self._finished:
            return []
        self._finished = True
        return self._decide(None)
