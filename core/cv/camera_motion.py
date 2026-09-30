from typing import Any

import cv2
import numpy as np


def estimate_camera_motion(
    frame1: np.ndarray,
    frame2: np.ndarray,
) -> dict[str, Any]:
    """基于特征点匹配估计两帧间的相机运动参数。"""
    gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

    detector = cv2.SIFT_create()
    kp1, des1 = detector.detectAndCompute(gray1, None)
    kp2, des2 = detector.detectAndCompute(gray2, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return {
            "translation_x": 0.0,
            "translation_y": 0.0,
            "scale_ratio": 1.0,
            "rotation_deg": 0.0,
            "confidence": 0.0,
        }

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    matches = matcher.knnMatch(des1, des2, k=2)

    good = []
    for pair in matches:
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
            good.append(pair[0])

    if len(good) < 4:
        return {
            "translation_x": 0.0,
            "translation_y": 0.0,
            "scale_ratio": 1.0,
            "rotation_deg": 0.0,
            "confidence": 0.0,
        }

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    matrix, inliers = cv2.estimateAffinePartial2D(src_pts, dst_pts, method=cv2.RANSAC)

    if matrix is None:
        return {
            "translation_x": 0.0,
            "translation_y": 0.0,
            "scale_ratio": 1.0,
            "rotation_deg": 0.0,
            "confidence": 0.0,
        }

    tx = float(matrix[0, 2])
    ty = float(matrix[1, 2])
    scale_x = float(np.sqrt(matrix[0, 0] ** 2 + matrix[0, 1] ** 2))
    scale_y = float(np.sqrt(matrix[1, 0] ** 2 + matrix[1, 1] ** 2))
    scale_ratio = (scale_x + scale_y) / 2.0
    rotation_rad = float(np.arctan2(matrix[1, 0], matrix[0, 0]))
    rotation_deg = float(np.degrees(rotation_rad))

    confidence = float(inliers.sum() / len(good)) if inliers is not None else 0.0

    return {
        "translation_x": round(tx, 2),
        "translation_y": round(ty, 2),
        "scale_ratio": round(scale_ratio, 4),
        "rotation_deg": round(rotation_deg, 2),
        "confidence": round(confidence, 3),
    }
