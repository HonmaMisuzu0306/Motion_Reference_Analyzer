from typing import Any

import cv2
import numpy as np

from cv.feature_tracker import detect_and_track_features
from cv.thresholds import (
    MAX_SINGLE_PAIR_ROTATION_DEG,
    MAX_SINGLE_PAIR_SCALE,
    MAX_SINGLE_PAIR_TRANSLATION_RATIO,
    MIN_INLIER_RATIO,
    MIN_TRACKED_FEATURES,
    RANSAC_THRESHOLD,
)


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

    tx = float(matrix[0, 2])
    ty = float(matrix[1, 2])
    scale_x = float(np.hypot(matrix[0, 0], matrix[0, 1]))
    scale_y = float(np.hypot(matrix[1, 0], matrix[1, 1]))
    scale_ratio = (scale_x + scale_y) / 2.0
    rotation_rad = float(np.arctan2(matrix[1, 0], matrix[0, 0]))
    rotation_deg = float(np.degrees(rotation_rad))

    h, w = frame1.shape[:2]
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
        "valid": True,
    }
