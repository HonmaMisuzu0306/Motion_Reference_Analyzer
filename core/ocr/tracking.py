"""跨帧文字追踪（Text Tracking）。

将多帧 OCR 结果按文字相似性与位置重叠合并为 TextTrack。
"""

from __future__ import annotations

import difflib
import uuid
from typing import Any

from schemas.typography import (
    Appearance,
    ColorObservation,
    NormalizedBBox,
    TextMotion,
    TextRegion,
    TextTrack,
    TypographyAnalysis,
)


def _iou(a: NormalizedBBox, b: NormalizedBBox) -> float:
    """计算两个归一化 bbox 的 IoU。"""
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.width, b.x + b.width)
    y2 = min(a.y + a.height, b.y + b.height)
    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter = inter_w * inter_h
    area_a = a.width * a.height
    area_b = b.width * b.height
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _center_distance(a: NormalizedBBox, b: NormalizedBBox) -> float:
    """归一化中心点距离。"""
    cx_a = a.x + a.width / 2
    cy_a = a.y + a.height / 2
    cx_b = b.x + b.width / 2
    cy_b = b.y + b.height / 2
    return ((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2) ** 0.5


def _text_similarity(a: str, b: str) -> float:
    """基于 difflib 的归一化文本相似度（0.0 ~ 1.0）。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _match_region_to_tracks(
    region: TextRegion,
    tracks: list[TextTrack],
    text_threshold: float = 0.6,
    iou_threshold: float = 0.2,
    center_threshold: float = 0.15,
) -> TextTrack | None:
    """将当前区域匹配到已有 Track。

    匹配规则：文字相似度 >= threshold 且 (IoU >= threshold 或 中心距离 <= center_threshold)。
    返回最佳匹配 Track。
    """
    best_track: TextTrack | None = None
    best_score = 0.0

    for track in tracks:
        text_sim = _text_similarity(region.normalized_text, track.canonical_text)
        last_bbox = (
            track.regions[-1].bbox_normalized
            if track.regions
            else track.average_bbox
        )
        iou = _iou(region.bbox_normalized, last_bbox)
        dist = _center_distance(region.bbox_normalized, last_bbox)

        spatial_ok = iou >= iou_threshold or dist <= center_threshold
        if text_sim < text_threshold or not spatial_ok:
            continue

        # 综合得分：文字相似度权重更高
        score = text_sim * 0.7 + (1 - min(dist, 1.0)) * 0.3
        if score > best_score:
            best_score = score
            best_track = track

    return best_track


def _average_bbox(regions: list[TextRegion]) -> NormalizedBBox:
    """对区域内所有 bbox 做平均。"""
    if not regions:
        return NormalizedBBox()
    xs = [r.bbox_normalized.x for r in regions]
    ys = [r.bbox_normalized.y for r in regions]
    ws = [r.bbox_normalized.width for r in regions]
    hs = [r.bbox_normalized.height for r in regions]
    n = len(regions)
    return NormalizedBBox(
        x=round(sum(xs) / n, 4),
        y=round(sum(ys) / n, 4),
        width=round(sum(ws) / n, 4),
        height=round(sum(hs) / n, 4),
    )


def _average_confidence(regions: list[TextRegion]) -> float:
    if not regions:
        return 0.0
    return round(sum(r.confidence for r in regions) / len(regions), 4)


def _decide_movement(
    regions: list[TextRegion],
    movement_threshold: float = 0.02,
    scale_threshold: float = 0.02,
) -> TextMotion:
    """根据首/尾 bbox 变化判断文字运动。"""
    if len(regions) < 2:
        return "static"

    first = regions[0].bbox_normalized
    last = regions[-1].bbox_normalized

    first_cx = first.x + first.width / 2
    first_cy = first.y + first.height / 2
    last_cx = last.x + last.width / 2
    last_cy = last.y + last.height / 2

    dx = last_cx - first_cx
    dy = last_cy - first_cy
    dw = last.width - first.width

    abs_dx = abs(dx)
    abs_dy = abs(dy)
    abs_dw = abs(dw)

    motion: TextMotion = "static"
    if abs_dw > scale_threshold and abs_dw > abs_dx and abs_dw > abs_dy:
        motion = "scale_in" if dw > 0 else "scale_out"
    elif abs_dx > movement_threshold or abs_dy > movement_threshold:
        if abs_dx >= abs_dy:
            motion = "slide_right" if dx > 0 else "slide_left"
        else:
            motion = "slide_down" if dy > 0 else "slide_up"

    return motion


def _decide_appearance(
    regions: list[TextRegion],
    confidence_ramp_threshold: float = 0.15,
) -> Appearance:
    """根据首/尾区域置信度/尺寸变化判断出现/消失方式。"""
    if len(regions) < 2:
        return "hard_cut"

    first = regions[0]
    last = regions[-1]
    first_area = first.bbox_normalized.width * first.bbox_normalized.height
    last_area = last.bbox_normalized.width * last.bbox_normalized.height
    conf_diff = last.confidence - first.confidence
    area_diff = last_area - first_area

    movement = _decide_movement(regions)

    # 尺寸持续增长/减小 → scale
    area_growth = last_area - first_area
    if abs(area_growth) > confidence_ramp_threshold:
        return "scale"

    # 位置移动 → slide
    if movement != "static":
        return "slide"

    # 置信度/面积逐步增强 → fade
    if abs(conf_diff) > confidence_ramp_threshold or abs(area_diff) > 0.02:
        return "fade"

    # 稳定出现 → hard_cut（最保守，证据不足时不猜 mask_like_reveal）
    return "hard_cut"


def build_text_tracks(
    frame_results: list[dict[str, Any]],
    text_threshold: float = 0.6,
    iou_threshold: float = 0.1,
    center_threshold: float = 0.25,
    max_gap_seconds: float | None = None,
) -> list[TextTrack]:
    """将多帧 OCR 结果合并为 TextTrack。

    Args:
        frame_results: 每个元素为 {"timestamp": float, "regions": list[TextRegion]}。
    """
    tracks: list[TextTrack] = []
    if max_gap_seconds is None:
        timestamps = sorted({frame.get("timestamp", 0.0) for frame in frame_results})
        intervals = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
        # Allow one missed sample, including sparsely sampled long shots.
        max_gap_seconds = max(1.0, 2 * min(intervals)) if intervals else 1.0

    for frame in frame_results:
        timestamp = frame.get("timestamp", 0.0)
        regions = frame.get("regions", [])
        matched_track_ids: set[str] = set()

        for region in regions:
            track = _match_region_to_tracks(
                region,
                [t for t in tracks if t.track_id not in matched_track_ids
                 and 0 <= timestamp - t.end_time <= max_gap_seconds],
                text_threshold=text_threshold,
                iou_threshold=iou_threshold,
                center_threshold=center_threshold,
            )

            if track is None:
                track = TextTrack(
                    track_id=f"track_{uuid.uuid4().hex[:8]}",
                    canonical_text=region.normalized_text,
                    language=region.language,
                    start_time=timestamp,
                    end_time=timestamp,
                    regions=[region],
                    movement="unknown",
                    appearance="unknown",
                )
                tracks.append(track)
            else:
                track.regions.append(region)
                track.start_time = min(track.start_time, timestamp)
                track.end_time = max(track.end_time, timestamp)
                # 更新 canonical_text 为出现次数最多的文本
                counts: dict[str, int] = {}
                for r in track.regions:
                    counts[r.normalized_text] = counts.get(r.normalized_text, 0) + 1
                track.canonical_text = max(counts, key=counts.get)
                # 语言：若包含 ja 优先保留 ja
                if any(r.language == "ja" for r in track.regions):
                    track.language = "ja"
            matched_track_ids.add(track.track_id)

    # 后处理：计算时间、位置、运动、出现方式
    for track in tracks:
        if not track.regions:
            continue
        track.duration = round(track.end_time - track.start_time, 3)
        track.average_confidence = _average_confidence(track.regions)
        track.average_bbox = _average_bbox(track.regions)
        track.frame_count = len(track.regions)
        track.movement = _decide_movement(track.regions)
        track.appearance = _decide_appearance(track.regions)

        # 保留原文字用于展示（取置信度最高的原始文本）
        best_region = max(track.regions, key=lambda r: r.confidence)
        if track.canonical_text != best_region.normalized_text:
            track.canonical_text = best_region.normalized_text

    # 按开始时间排序
    tracks.sort(key=lambda t: t.start_time)
    return tracks


def attach_typography_analysis(
    track: TextTrack,
    analysis: TypographyAnalysis,
    color: ColorObservation | None = None,
) -> None:
    """将 Qwen Typography 语义分析结果附加到 Track。"""
    track.typography_analysis = analysis
    if color is not None:
        track.color_observation = color
