from typing import Any

import cv2
import numpy as np


def estimate_optical_flow(
    frame1: np.ndarray,
    frame2: np.ndarray,
    method: str = "farneback",
) -> dict[str, Any]:
    """估计两帧之间的光流并返回基本统计信息。"""
    gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

    if method == "farneback":
        flow = cv2.calcOpticalFlowFarneback(
            gray1, gray2, None, 0.5, 3, 15, 3, 5, 1.2, 0,
        )
    else:
        raise ValueError(f"不支持的光流方法: {method}")

    magnitude, angle = cv2.cartToPolar(flow[..., 0], flow[..., 1])

    return {
        "mean_magnitude": float(np.mean(magnitude)),
        "max_magnitude": float(np.max(magnitude)),
        "mean_angle": float(np.mean(angle)),
        "std_magnitude": float(np.std(magnitude)),
    }
