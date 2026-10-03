from typing import Any

import cv2
import numpy as np

from cv.thresholds import (
    FEATURE_MIN_DISTANCE,
    FEATURE_QUALITY,
    LUCAS_KANADE_LEVELS,
    LUCAS_KANADE_WINDOW,
    MIN_FEATURES_TO_TRACK,
)


def detect_and_track_features(
    gray1: np.ndarray,
    gray2: np.ndarray,
    max_corners: int = 200,
) -> dict[str, Any]:
    """使用 Shi-Tomasi + LK 光流跟踪相邻帧特征点。

    返回匹配后的 src_pts/dst_pts、跟踪数量、状态标志。
    """
    if gray1.shape != gray2.shape:
        raise ValueError("两帧灰度图尺寸必须一致")

    features = cv2.goodFeaturesToTrack(
        gray1,
        maxCorners=max_corners,
        qualityLevel=FEATURE_QUALITY,
        minDistance=FEATURE_MIN_DISTANCE,
        blockSize=7,
    )

    if features is None or len(features) < MIN_FEATURES_TO_TRACK:
        return {
            "src_pts": None,
            "dst_pts": None,
            "tracked": 0,
            "success": False,
        }

    next_pts, status, err = cv2.calcOpticalFlowPyrLK(
        gray1,
        gray2,
        features,
        None,
        winSize=(LUCAS_KANADE_WINDOW, LUCAS_KANADE_WINDOW),
        maxLevel=LUCAS_KANADE_LEVELS,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03),
    )

    if next_pts is None or status is None:
        return {
            "src_pts": None,
            "dst_pts": None,
            "tracked": 0,
            "success": False,
        }

    status = status.reshape(-1)
    good_src = features[status == 1]
    good_dst = next_pts[status == 1]

    if len(good_src) < MIN_FEATURES_TO_TRACK:
        return {
            "src_pts": None,
            "dst_pts": None,
            "tracked": len(good_src),
            "success": False,
        }

    return {
        "src_pts": good_src.reshape(-1, 1, 2),
        "dst_pts": good_dst.reshape(-1, 1, 2),
        "tracked": len(good_src),
        "success": True,
    }
