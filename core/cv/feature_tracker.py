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


def _supplement_sparse_tiles(gray: np.ndarray, features: np.ndarray) -> np.ndarray:
    """Look for quieter texture where one high-contrast layer monopolized the detector."""
    h, w = gray.shape
    additions = []
    points = features.reshape(-1, 2)
    columns, rows = 8, 6
    cell = (points[:, 0].astype(int) * columns // w
            + columns * (points[:, 1].astype(int) * rows // h))
    counts = np.bincount(cell, minlength=columns * rows)
    for index in np.flatnonzero(counts < 2):
        row, col = divmod(int(index), columns)
        x, right = (col * w + columns - 1) // columns, ((col + 1) * w + columns - 1) // columns
        y, bottom = (row * h + rows - 1) // rows, ((row + 1) * h + rows - 1) // rows
        if min(right - x, bottom - y) < 12:
            continue
        tile = gray[y:bottom, x:right]
        if tile.std() < 5:
            continue
        mask = np.full(tile.shape, 255, np.uint8)
        for px, py in points[cell == index]:
            cv2.circle(mask, (round(px - x), round(py - y)), FEATURE_MIN_DISTANCE, 0, -1)
        found = cv2.goodFeaturesToTrack(tile, 8, FEATURE_QUALITY, FEATURE_MIN_DISTANCE,
                                        mask=mask, blockSize=7)
        if found is not None:
            additions.append(found + np.array([x, y], dtype=np.float32))
    return np.concatenate([features, *additions]) if additions else features


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

    features = _supplement_sparse_tiles(gray1, features)
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

