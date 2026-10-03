import time
from pathlib import Path

import numpy as np

from cv.frame_sampler import sample_frames_for_cv
from cv.thresholds import (
    CONFIDENCE_WEIGHTS,
    MIN_FEATURES_TO_TRACK,
    MIN_VALID_PAIR_RATIO,
    MIN_VALID_PAIRS_ABSOLUTE,
    STRENGTH_THRESHOLDS,
)
from cv.transform import estimate_transform_between_frames
from schemas.measured_motion import FramePairTransform, MeasuredMotion, MotionStrength

SHAKE_AMPLITUDE_PX = 2.0


def _classify_strength(total_change: float) -> MotionStrength:
    """根据累计变化幅度对运动强度做粗略分级。"""
    if total_change < STRENGTH_THRESHOLDS["none"]:
        return "none"
    if total_change < STRENGTH_THRESHOLDS["very_light"]:
        return "very_light"
    if total_change < STRENGTH_THRESHOLDS["light"]:
        return "light"
    if total_change < STRENGTH_THRESHOLDS["medium"]:
        return "medium"
    return "strong"


def _compute_stability(pairs: list[FramePairTransform]) -> float:
    """计算变换一致性 / 稳定性分数。"""
    if len(pairs) < 2:
        return 1.0

    scales = np.array([p.scale_ratio for p in pairs])
    rots = np.array([p.rotation_deg for p in pairs])
    txs = np.array([p.dx_px for p in pairs])
    tys = np.array([p.dy_px for p in pairs])

    # 用相对标准差衡量波动；越稳定越接近 1
    def _stab(values: np.ndarray) -> float:
        mean = float(np.mean(np.abs(values)))
        std = float(np.std(values))
        if mean < 1e-6:
            return 1.0
        coeff_var = std / mean
        return float(np.clip(1.0 - coeff_var, 0.0, 1.0))

    stab_scale = _stab(scales)
    stab_rot = _stab(rots)
    stab_tx = _stab(txs)
    stab_ty = _stab(tys)

    return float(np.mean([stab_scale, stab_rot, stab_tx, stab_ty]))


def _compute_shake_score(pairs: list[FramePairTransform]) -> float:
    """基于方向/旋转频繁反转和相对小幅位移计算 shake score。"""
    if len(pairs) < 3:
        return 0.0

    txs = [p.dx_px for p in pairs]
    tys = [p.dy_px for p in pairs]
    rots = [p.rotation_deg for p in pairs]

    def _flip_ratio(values: list[float]) -> float:
        flips = 0
        for i in range(1, len(values)):
            if values[i - 1] != 0 and values[i] * values[i - 1] < 0:
                flips += 1
        return flips / (len(values) - 1)

    tx_flips = _flip_ratio(txs)
    ty_flips = _flip_ratio(tys)
    rot_flips = _flip_ratio(rots)

    avg_mag = np.mean([np.hypot(p.dx_px, p.dy_px) for p in pairs])
    amplitude_score = float(np.clip(avg_mag / SHAKE_AMPLITUDE_PX, 0.0, 1.0))

    direction_score = (tx_flips + ty_flips) / 2.0
    rotation_score = rot_flips

    return float(np.clip(
        direction_score * 0.5
        + rotation_score * 0.2
        + amplitude_score * 0.3,
        0.0,
        1.0,
    ))


def _compute_confidence(
    pairs: list[FramePairTransform],
    valid_pairs: list[FramePairTransform],
    total_pair_count: int,
    stability: float,
) -> float:
    """综合 inlier ratio、特征数量、有效帧对比例、稳定性计算置信度。"""
    if not valid_pairs:
        return 0.0

    avg_inlier = float(np.mean([p.inlier_ratio for p in valid_pairs]))
    avg_tracked = float(np.mean([p.tracked_features for p in valid_pairs]))
    tracked_score = float(np.clip(avg_tracked / MIN_FEATURES_TO_TRACK, 0.0, 1.0))
    valid_ratio = len(valid_pairs) / total_pair_count if total_pair_count > 0 else 0.0

    score = (
        avg_inlier * CONFIDENCE_WEIGHTS["inlier_ratio"]
        + tracked_score * CONFIDENCE_WEIGHTS["tracked_features"]
        + valid_ratio * CONFIDENCE_WEIGHTS["valid_pair_ratio"]
        + stability * CONFIDENCE_WEIGHTS["stability"]
    )
    return float(np.clip(score, 0.0, 1.0))


def analyze_shot_motion(
    video_path: str | Path,
    start_time: float,
    end_time: float,
    original_width: int,
    original_height: int,
    target_fps: float = 8,
    max_long_edge: int = 720,
) -> MeasuredMotion:
    """测量单个 Shot 的全局运动。"""
    start_ts = time.perf_counter()

    try:
        frames = sample_frames_for_cv(
            video_path,
            start_time,
            end_time,
            target_fps=target_fps,
            max_long_edge=max_long_edge,
        )
    except Exception as exc:
        return MeasuredMotion(
            status="failed",
            message=f"帧采样失败: {exc}",
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    sample_count = len(frames)
    if sample_count < 2:
        return MeasuredMotion(
            status="failed",
            message=f"CV 采样帧不足: {sample_count}",
            sample_count=sample_count,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    pairs: list[FramePairTransform] = []
    valid_pairs: list[FramePairTransform] = []
    insufficient_features_count = 0

    for i in range(sample_count - 1):
        result = estimate_transform_between_frames(frames[i]["image"], frames[i + 1]["image"])

        pair = FramePairTransform(
            dx_px=result["dx_px"],
            dy_px=result["dy_px"],
            scale_ratio=result["scale_ratio"],
            rotation_deg=result["rotation_deg"],
            inlier_ratio=result["inlier_ratio"],
            tracked_features=result["tracked_features"],
        )
        pairs.append(pair)

        if result["valid"]:
            valid_pairs.append(pair)
        elif result["tracked_features"] < MIN_FEATURES_TO_TRACK:
            insufficient_features_count += 1

    total_pair_count = len(pairs)

    # 如果所有帧对都特征不足，判定为低纹理
    if insufficient_features_count == total_pair_count:
        return MeasuredMotion(
            status="insufficient_features",
            message="所有帧对特征点不足，无法估计运动",
            sample_count=sample_count,
            total_pair_count=total_pair_count,
            valid_pair_count=0,
            pairs=pairs,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    # 有效帧对太少
    valid_ratio = len(valid_pairs) / total_pair_count if total_pair_count > 0 else 0.0
    if (
        len(valid_pairs) < MIN_VALID_PAIRS_ABSOLUTE
        or valid_ratio < MIN_VALID_PAIR_RATIO
    ):
        return MeasuredMotion(
            status="too_few_valid_pairs",
            message=f"有效帧对过少: {len(valid_pairs)}/{total_pair_count}",
            sample_count=sample_count,
            total_pair_count=total_pair_count,
            valid_pair_count=len(valid_pairs),
            pairs=pairs,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    # 累计运动（使用有效帧对）
    total_dx = float(np.sum([p.dx_px for p in valid_pairs]))
    total_dy = float(np.sum([p.dy_px for p in valid_pairs]))
    # 缩放是乘性累计
    scale_ratio = float(np.prod([p.scale_ratio for p in valid_pairs])) if valid_pairs else 1.0
    total_rotation = float(np.sum([p.rotation_deg for p in valid_pairs]))

    # 归一化到原始分辨率
    long_edge = max(original_width, original_height)
    analysis_long_edge = max(frames[0]["image"].shape[:2])
    scale_to_original = long_edge / analysis_long_edge if analysis_long_edge > 0 else 1.0

    translation_x_px = total_dx * scale_to_original
    translation_y_px = total_dy * scale_to_original
    translation_x_ratio = translation_x_px / original_width if original_width > 0 else 0.0
    translation_y_ratio = translation_y_px / original_height if original_height > 0 else 0.0

    stability = _compute_stability(valid_pairs)
    shake_score = _compute_shake_score(valid_pairs)
    confidence = _compute_confidence(pairs, valid_pairs, total_pair_count, stability)

    # 运动强度：综合平移、缩放、旋转的累计绝对变化
    total_change = max(
        abs(translation_x_ratio),
        abs(translation_y_ratio),
        abs(scale_ratio - 1.0),
        abs(total_rotation) / 360.0,
    )
    motion_strength = _classify_strength(total_change)

    return MeasuredMotion(
        status="ok",
        method="goodFeaturesToTrack_LK_affine",
        sample_count=sample_count,
        total_pair_count=total_pair_count,
        valid_pair_count=len(valid_pairs),
        translation_x_px=round(translation_x_px, 2),
        translation_y_px=round(translation_y_px, 2),
        translation_x_ratio=round(translation_x_ratio, 4),
        translation_y_ratio=round(translation_y_ratio, 4),
        scale_ratio=round(scale_ratio, 4),
        scale_change_percent=round((scale_ratio - 1.0) * 100, 2),
        rotation_deg=round(total_rotation, 2),
        motion_strength=motion_strength,
        stability=round(stability, 3),
        shake_score=round(shake_score, 3),
        confidence=round(confidence, 3),
        pairs=pairs,
        cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
    )
