from typing import Any

import cv2
import numpy as np

from cv.feature_tracker import detect_and_track_features
from cv.thresholds import (
    MAX_SINGLE_PAIR_ROTATION_DEG,
    MAX_SINGLE_PAIR_SCALE,
    MAX_SINGLE_PAIR_TRANSLATION_RATIO,
    MIN_INLIER_RATIO,
    MIN_SUPPORT_CENTRAL_SPAN,
    MIN_SUPPORT_HULL_FRACTION,
    MIN_TRACKED_FEATURES,
    RANSAC_THRESHOLD,
)


def _spatial_support(src, dst, mask, width, height):
    """Measure the spread of visible model inliers in both endpoint frames."""
    size = np.array([width, height], dtype=np.float32)
    a, b = src.reshape(-1, 2) / size, dst.reshape(-1, 2) / size
    visible = mask.ravel().astype(bool) & ((a >= 0) & (a < 1) & (b >= 0) & (b < 1)).all(axis=1)
    if visible.sum() < MIN_TRACKED_FEATURES:
        return 0., False
    area, span = 1., 1.
    for points in (a[visible], b[visible]):
        area = min(area, cv2.contourArea(cv2.convexHull(points)))
        # Isolated matches at the extremes can inflate a hull around a tiny moving patch.
        lo, hi = np.percentile(points, [10, 90], axis=0)
        span = min(span, float(np.min(hi - lo)))
    return area, area >= MIN_SUPPORT_HULL_FRACTION and span >= MIN_SUPPORT_CENTRAL_SPAN


def _edge_coverage(points, width, height):
    """Count frame corners with multiple supporting tracks within the outer eighth."""
    x, y = points.reshape(-1, 2).T / np.array([[width], [height]])
    visible = (0 <= x) & (x < 1) & (0 <= y) & (y < 1)
    return sum(np.count_nonzero(visible & horizontal & vertical) >= 2
               for horizontal in (x <= 1 / 8, x >= 7 / 8)
               for vertical in (y <= 1 / 8, y >= 7 / 8))


def _resolve_competing_model(src, dst, primary, mask, width, height):
    """Prefer uniquely frame-wide support over a second independently moving plane.

    A few bad tracks are not a second plane. Fit only points whose displacement
    contradicts the primary model, require a substantial coherent set and
    verify observable support in both images before using the alternate fit.
    """
    def errors(matrix):
        projected = cv2.transform(src.reshape(-1, 1, 2), matrix)
        return np.linalg.norm(projected - dst.reshape(-1, 1, 2), axis=2).ravel()

    # A 3 px global fit can absorb two slow pans into one false scale. Search
    # for two tighter consensuses only when enough residuals justify the check.
    tolerance = .8
    required = max(16, int(np.ceil(.12 * len(src))))
    if np.count_nonzero(errors(primary) > tolerance) < required:
        return primary, mask, False
    first, first_inliers = cv2.estimateAffinePartial2D(src, dst, ransacReprojThreshold=tolerance)
    if first is None or first_inliers is None or int(first_inliers.sum()) < required:
        return primary, mask, False
    conflicting = errors(first) > 2 * tolerance
    if np.count_nonzero(conflicting) < required:
        return primary, mask, False
    other, inliers = cv2.estimateAffinePartial2D(src[conflicting], dst[conflicting],
                                                 ransacReprojThreshold=tolerance)
    if other is None or inliers is None or int(inliers.sum()) < required:
        return primary, mask, False
    other_mask = np.zeros(len(src), dtype=bool)
    other_mask[conflicting] = inliers.ravel().astype(bool)
    main_mask = first_inliers.ravel().astype(bool)
    if np.count_nonzero(main_mask & (errors(other) > 2 * tolerance)) < required:
        return primary, mask, False
    _, main_spread = _spatial_support(src, dst, main_mask, width, height)
    _, other_spread = _spatial_support(src, dst, other_mask, width, height)
    main_edges = min(_edge_coverage(points[main_mask], width, height) for points in (src, dst))
    other_edges = min(_edge_coverage(points[other_mask], width, height) for points in (src, dst))
    if main_spread and main_edges >= 3 and (not other_spread or other_edges <= 1):
        return first, first_inliers, False
    if other_spread and other_edges >= 3 and (not main_spread or main_edges <= 1):
        if other_mask.mean() >= MIN_INLIER_RATIO:
            return other, other_mask, False
    if not other_spread and main_spread:
        return primary, mask, False
    return primary, mask, True


def _refine_consensus(src, dst, matrix, mask):
    """Remove bounded-fit bias from a small minority of inconsistent tracks."""
    selected = mask.ravel().astype(bool)
    a, b = src[selected], dst[selected]
    robust, keep = cv2.estimateAffinePartial2D(a, b, method=cv2.LMEDS)
    if robust is None or keep is None:
        return matrix, mask
    keep = keep.ravel().astype(bool)
    # Refinement may trim a minority (e.g. a small stationary HUD); it must
    # never replace the already selected motion with another competing plane.
    minimum = max(MIN_TRACKED_FEATURES, MIN_INLIER_RATIO * len(src), .75 * len(a))
    if keep.all() or keep.sum() < minimum:
        return matrix, mask

    def median_error(model):
        difference = cv2.transform(a.reshape(-1, 1, 2), model) - b.reshape(-1, 1, 2)
        return np.median(np.linalg.norm(difference, axis=2))

    if median_error(robust) >= median_error(matrix):
        return matrix, mask
    selected[selected] = keep
    return robust, selected


def estimate_transform_between_frames(
    frame1: np.ndarray,
    frame2: np.ndarray,
) -> dict[str, Any]:
    """估计两帧间的二维相似变换（平移 + 缩放 + 旋转）。

    frame1/frame2 为 BGR 图像；函数内部转为灰度处理。
    返回包含 dx_px, dy_px, scale_ratio, rotation_deg, confidence 的字典。
    """
    gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

    return estimate_transform_between_grays(gray1, gray2)


def estimate_transform_between_grays(gray1: np.ndarray, gray2: np.ndarray) -> dict[str, Any]:
    track_result = detect_and_track_features(gray1, gray2)
    if not track_result["success"]:
        return {
            "dx_px": 0.0,
            "dy_px": 0.0,
            "scale_ratio": 1.0,
            "rotation_deg": 0.0,
            "inlier_ratio": 0.0,
            "tracked_features": track_result["tracked"],
            "valid": False,
        }

    src_pts = track_result["src_pts"]
    dst_pts = track_result["dst_pts"]

    matrix, inliers = cv2.estimateAffinePartial2D(
        src_pts,
        dst_pts,
        method=cv2.RANSAC,
        ransacReprojThreshold=RANSAC_THRESHOLD,
    )

    if matrix is None:
        return {
            "dx_px": 0.0,
            "dy_px": 0.0,
            "scale_ratio": 1.0,
            "rotation_deg": 0.0,
            "inlier_ratio": 0.0,
            "tracked_features": track_result["tracked"],
            "valid": False,
        }

    inlier_count = int(inliers.sum()) if inliers is not None else 0
    tracked = track_result["tracked"]
    inlier_ratio = inlier_count / tracked if tracked > 0 else 0.0

    if inlier_ratio < MIN_INLIER_RATIO or inlier_count < MIN_TRACKED_FEATURES:
        return {
            "dx_px": 0.0,
            "dy_px": 0.0,
            "scale_ratio": 1.0,
            "rotation_deg": 0.0,
            "inlier_ratio": inlier_ratio,
            "tracked_features": tracked,
            "valid": False,
        }

    h, w = gray1.shape
    matrix, inliers, mixed = _resolve_competing_model(src_pts, dst_pts, matrix, inliers, w, h)
    area, distributed = _spatial_support(src_pts, dst_pts, inliers, w, h)
    if distributed and not mixed:
        matrix, refined_inliers = _refine_consensus(src_pts, dst_pts, matrix, inliers)
        if refined_inliers is not inliers:
            inliers = refined_inliers
            area, distributed = _spatial_support(src_pts, dst_pts, inliers, w, h)
    inlier_ratio = float(inliers.sum()) / tracked
    tx = float(matrix[0, 2])
    ty = float(matrix[1, 2])
    scale_x = float(np.hypot(matrix[0, 0], matrix[0, 1]))
    scale_y = float(np.hypot(matrix[1, 0], matrix[1, 1]))
    scale_ratio = (scale_x + scale_y) / 2.0
    rotation_rad = float(np.arctan2(matrix[1, 0], matrix[0, 0]))
    rotation_deg = float(np.degrees(rotation_rad))

    translation_ratio = np.hypot(tx, ty) / max(w, h)

    # 剔除异常帧对（切镜、转场、严重遮挡）
    if (
        scale_ratio > MAX_SINGLE_PAIR_SCALE
        or scale_ratio < 1.0 / MAX_SINGLE_PAIR_SCALE
        or abs(rotation_deg) > MAX_SINGLE_PAIR_ROTATION_DEG
        or translation_ratio > MAX_SINGLE_PAIR_TRANSLATION_RATIO
    ):
        return {
            "dx_px": tx,
            "dy_px": ty,
            "scale_ratio": scale_ratio,
            "rotation_deg": rotation_deg,
            "inlier_ratio": inlier_ratio,
            "tracked_features": tracked,
            "valid": False,
        }

    return {
        "dx_px": tx,
        "dy_px": ty,
        "scale_ratio": scale_ratio,
        "rotation_deg": rotation_deg,
        "inlier_ratio": inlier_ratio,
        "tracked_features": tracked,
        "support_area_ratio": area,
        "localized_support": not distributed and not mixed,
        "mixed_support": mixed,
        "valid": distributed and not mixed,
    }
