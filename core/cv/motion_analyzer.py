import time
from pathlib import Path

import numpy as np

from cv.frame_sampler import iter_frames_for_cv
from cv.long_baseline import LongBaselineCheck
from cv.motion_quality import motion_quality
from cv.thresholds import (
    CONFIDENCE_WEIGHTS,
    MIN_FEATURES_TO_TRACK,
    MIN_VALID_PAIR_RATIO,
    MIN_VALID_PAIRS_ABSOLUTE,
    STRENGTH_THRESHOLDS,
)
from cv.trajectory import compose_trajectory
from cv.transform import estimate_transform_between_frames
from schemas.measured_motion import FramePairTransform, MeasuredMotion, MotionStrength


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
    started = time.perf_counter()
    measured = _measure_once(video_path, start_time, end_time, original_width, original_height,
                             target_fps, max_long_edge)
    if (0 < end_time - start_time <= 1 and 0 < target_fps <= 8
            and (measured.status in ('too_few_valid_pairs', 'incomplete_tracking')
                 or (measured.status == 'localized_support'
                     and measured.spatially_limited_pair_count < measured.total_pair_count))):
        dense = _measure_once(video_path, start_time, end_time, original_width, original_height,
                              target_fps * 2, max_long_edge)
        if dense.status == 'ok':
            measured = dense
        measured.cv_analysis_ms = int((time.perf_counter() - started) * 1000)
    return measured


def _measure_once(video_path, start_time, end_time, original_width, original_height,
                  target_fps, max_long_edge) -> MeasuredMotion:
    start_ts = time.perf_counter()
    if original_width <= 0 or original_height <= 0:
        return MeasuredMotion(status='failed', message='原始画面尺寸无效')

    try:
        frames = iter(iter_frames_for_cv(
            video_path,
            start_time,
            end_time,
            target_fps=target_fps,
            max_long_edge=max_long_edge,
        ))
        previous = next(frames, None)
    except Exception as exc:
        return MeasuredMotion(
            status="failed",
            message=f"帧采样失败: {exc}",
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    sample_count = int(previous is not None)
    analysis_height, analysis_width = previous['image'].shape[:2] if previous is not None else (0, 0)
    pairs: list[FramePairTransform] = []
    valid_pairs: list[FramePairTransform] = []
    insufficient_features_count = 0
    localized_count = mixed_count = 0
    long_baseline = LongBaselineCheck(start_time, end_time, target_fps)

    try:
        while previous is not None:
            try:
                current = next(frames, None)
            except Exception as exc:
                return MeasuredMotion(
                    status='failed', message=f'帧采样失败: {exc}', sample_count=sample_count,
                    cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
                )
            if current is None:
                break
            sample_count += 1
            result = estimate_transform_between_frames(previous['image'], current['image'])
            long_baseline.observe(previous, current, result)
            pair = FramePairTransform(
                start_time=previous['timestamp'], end_time=current['timestamp'],
                valid=result['valid'], dx_px=result['dx_px'], dy_px=result['dy_px'],
                scale_ratio=result['scale_ratio'], rotation_deg=result['rotation_deg'],
                inlier_ratio=result['inlier_ratio'], tracked_features=result['tracked_features'],
                support_area_ratio=result.get('support_area_ratio'),
            )
            pairs.append(pair)
            if result['valid']:
                valid_pairs.append(pair)
            elif result.get('mixed_support'):
                mixed_count += 1
            elif result.get('localized_support'):
                localized_count += 1
            elif result['tracked_features'] < MIN_FEATURES_TO_TRACK:
                insufficient_features_count += 1
            previous = current
    finally:
        close = getattr(frames, 'close', None)
        if close is not None:
            close()
    # Keep only scalar measurements and composed matrices beyond the streaming pass.
    previous = current = None
    if sample_count < 2:
        return MeasuredMotion(
            status='failed', message=f'CV 采样帧不足: {sample_count}', sample_count=sample_count,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    total_pair_count = len(pairs)
    if long_baseline.conflict_count >= 2 and len(valid_pairs) == total_pair_count:
        return MeasuredMotion(
            status='mixed_support', sampling_target_fps=target_fps,
            frame_width=original_width, frame_height=original_height, translation_reference='frame_center',
            message=f'{long_baseline.check_count} 个跨帧区间中有 {long_baseline.conflict_count} 个检测到相互冲突的区域运动，无法确认整幅画面的变换。',
            long_baseline_check_count=long_baseline.check_count,
            long_baseline_conflict_count=long_baseline.conflict_count,
            sample_count=sample_count, total_pair_count=total_pair_count, valid_pair_count=len(valid_pairs),
            pairs=pairs, cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )
    trajectory = compose_trajectory(
        pairs, analysis_width=analysis_width, analysis_height=analysis_height,
        original_width=original_width, original_height=original_height,
    )
    evidence = {
        'sampling_target_fps': target_fps,
        'long_baseline_check_count': long_baseline.check_count,
        'long_baseline_conflict_count': long_baseline.conflict_count,
        'frame_width': original_width, 'frame_height': original_height,
        'translation_reference': 'frame_center',
        'trajectory_status': 'complete' if len(valid_pairs) == total_pair_count else 'partial',
        'trajectory': trajectory,
    }

    if mixed_count:
        return MeasuredMotion(
            status='mixed_support', **evidence,
            message=f'{mixed_count}/{total_pair_count} 个帧对存在相互冲突的区域运动，无法确认整幅画面的变换。',
            sample_count=sample_count, total_pair_count=total_pair_count, valid_pair_count=len(valid_pairs),
            mixed_support_pair_count=mixed_count, spatially_limited_pair_count=localized_count, pairs=pairs,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )
    if localized_count:
        return MeasuredMotion(
            status='localized_support', **evidence,
            message=f'{localized_count}/{total_pair_count} 个帧对的匹配点分布过于集中，无法确认整幅画面的运动。',
            sample_count=sample_count, total_pair_count=total_pair_count, valid_pair_count=len(valid_pairs),
            spatially_limited_pair_count=localized_count, pairs=pairs,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    # 如果所有帧对都特征不足，判定为低纹理
    if insufficient_features_count == total_pair_count:
        return MeasuredMotion(
            status="insufficient_features",
            **evidence,
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
            **evidence,
            message=f"有效帧对过少: {len(valid_pairs)}/{total_pair_count}",
            sample_count=sample_count,
            total_pair_count=total_pair_count,
            valid_pair_count=len(valid_pairs),
            pairs=pairs,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    if len(valid_pairs) != total_pair_count:
        return MeasuredMotion(
            status='incomplete_tracking', message='跟踪存在缺口；仅保留各连续片段，不能合成整镜头运动',
            sample_count=sample_count, total_pair_count=total_pair_count, valid_pair_count=len(valid_pairs),
            pairs=pairs, **evidence,
            cv_analysis_ms=int((time.perf_counter() - start_ts) * 1000),
        )

    last = trajectory[-1]
    translation_x_px, translation_y_px = last.translation_x_px, last.translation_y_px
    translation_x_ratio, translation_y_ratio = last.translation_x_ratio, last.translation_y_ratio
    scale_ratio, total_rotation = last.scale_ratio, last.rotation_deg

    stability, shake_score = motion_quality(
        trajectory, frame_width=original_width, frame_height=original_height,
    )
    confidence = _compute_confidence(pairs, valid_pairs, total_pair_count, stability)

    # 运动强度：综合平移、缩放、旋转的累计绝对变化
    total_change = max(max(abs(point.translation_x_ratio), abs(point.translation_y_ratio),
                           abs(point.scale_ratio - 1), abs(point.rotation_deg) / 360)
                       for point in trajectory)
    motion_strength = _classify_strength(total_change)

    return MeasuredMotion(
        status="ok",
        method="goodFeaturesToTrack_LK_affine_time_aware_center_v4",
        **evidence,
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
