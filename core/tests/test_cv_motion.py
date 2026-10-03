from pathlib import Path

import av
import cv2
import numpy as np

from cv.motion_analyzer import analyze_shot_motion
from cv.motion_fusion import fuse_motion
from cv.transform import estimate_transform_between_frames


def _create_synthetic_frame(
    size: tuple[int, int] = (720, 1280),
    textured: bool = True,
) -> np.ndarray:
    """创建带非周期纹理或纯色的合成帧。"""
    h, w = size
    if textured:
        rng = np.random.default_rng(42)
        # 多层随机块，避免周期性图案导致匹配歧义
        frame = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        for size_step in (80, 40, 20):
            mask = rng.integers(0, 256, (h // size_step + 2, w // size_step + 2, 3), dtype=np.uint8)
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
            frame = cv2.addWeighted(frame, 0.5, mask, 0.5, 0)
        return frame
    return np.full((h, w, 3), 128, dtype=np.uint8)


def _shift_frame(frame: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """平移图像。"""
    h, w = frame.shape[:2]
    matrix = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(frame, matrix, (w, h))


def _scale_frame(frame: np.ndarray, scale: float) -> np.ndarray:
    """以中心为基准缩放图像，保持输出尺寸不变。"""
    h, w = frame.shape[:2]
    scaled = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    sh, sw = scaled.shape[:2]

    if scale >= 1.0:
        # 放大后裁剪中心区域
        src_top = (sh - h) // 2
        src_left = (sw - w) // 2
        return scaled[src_top : src_top + h, src_left : src_left + w]

    # 缩小后居中填充
    top = (h - sh) // 2
    left = (w - sw) // 2
    output = np.zeros_like(frame)
    output[top : top + sh, left : left + sw] = scaled
    return output


def _rotate_frame(frame: np.ndarray, angle_deg: float) -> np.ndarray:
    """以中心为基准旋转图像。"""
    h, w = frame.shape[:2]
    center = (w / 2, h / 2)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    return cv2.warpAffine(frame, matrix, (w, h))


def test_static_frame_pair_returns_near_identity():
    frame = _create_synthetic_frame()
    result = estimate_transform_between_frames(frame, frame)

    assert result["valid"] is True
    assert abs(result["dx_px"]) < 1.0
    assert abs(result["dy_px"]) < 1.0
    assert abs(result["scale_ratio"] - 1.0) < 0.01
    assert abs(result["rotation_deg"]) < 0.1
    assert result["inlier_ratio"] > 0.25


def test_translation_frame_pair():
    frame1 = _create_synthetic_frame()
    frame2 = _shift_frame(frame1, 20, -10)
    result = estimate_transform_between_frames(frame1, frame2)

    assert result["valid"] is True
    assert result["dx_px"] > 12
    assert result["dx_px"] < 28
    assert result["dy_px"] < -5
    assert result["dy_px"] > -15


def test_scale_frame_pair():
    frame1 = _create_synthetic_frame()
    frame2 = _scale_frame(frame1, 1.10)
    result = estimate_transform_between_frames(frame1, frame2)

    assert result["valid"] is True
    assert result["scale_ratio"] > 1.05
    assert result["scale_ratio"] < 1.15


def test_rotation_frame_pair():
    frame1 = _create_synthetic_frame()
    frame2 = _rotate_frame(frame1, 3.0)
    result = estimate_transform_between_frames(frame1, frame2)

    assert result["valid"] is True
    assert abs(result["rotation_deg"]) > 1.5
    assert abs(result["rotation_deg"]) < 4.5


def test_low_texture_returns_insufficient_features():
    frame1 = _create_synthetic_frame(textured=False)
    frame2 = _shift_frame(frame1, 5, 0)
    result = estimate_transform_between_frames(frame1, frame2)

    assert result["valid"] is False
    assert result["tracked_features"] < 30


def _create_test_video_with_motion(
    path: Path,
    motion: str,
    duration: float = 1.0,
    fps: int = 24,
) -> Path:
    """创建带已知运动的测试视频。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 640, 360
    total_frames = int(duration * fps)
    base_frame = _create_synthetic_frame((height, width))

    with av.open(str(path), "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"

        for i in range(total_frames):
            t = i / (total_frames - 1) if total_frames > 1 else 0.0
            if motion == "static":
                frame = base_frame
            elif motion == "translation":
                frame = _shift_frame(base_frame, 20 * t, -10 * t)
            elif motion == "scale":
                frame = _scale_frame(base_frame, 1.0 + 0.10 * t)
            elif motion == "rotation":
                frame = _rotate_frame(base_frame, 3.0 * t)
            elif motion == "low_texture":
                low = _create_synthetic_frame((height, width), textured=False)
                frame = _shift_frame(low, 2 * t, 0)
            else:
                frame = base_frame

            av_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
            for packet in stream.encode(av_frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

    return path


class TestShotMotionAnalysis:
    def test_static_shot(self, tmp_path: Path):
        video = _create_test_video_with_motion(tmp_path / "static.mp4", "static")
        result = analyze_shot_motion(video, 0.0, 1.0, 640, 360)

        assert result.status == "ok"
        assert abs(result.scale_ratio - 1.0) < 0.01
        assert abs(result.rotation_deg) < 0.5
        assert abs(result.translation_x_px) < 2.0
        assert abs(result.translation_y_px) < 2.0
        assert result.confidence > 0.5

    def test_translation_shot(self, tmp_path: Path):
        video = _create_test_video_with_motion(tmp_path / "translation.mp4", "translation")
        result = analyze_shot_motion(video, 0.0, 1.0, 640, 360)

        assert result.status == "ok"
        # 方向正确
        assert result.translation_x_px > 0
        assert result.translation_y_px < 0

    def test_scale_shot(self, tmp_path: Path):
        video = _create_test_video_with_motion(tmp_path / "scale.mp4", "scale")
        result = analyze_shot_motion(video, 0.0, 1.0, 640, 360)

        assert result.status == "ok"
        assert result.scale_change_percent > 5.0
        assert result.scale_change_percent < 15.0

    def test_rotation_shot(self, tmp_path: Path):
        video = _create_test_video_with_motion(tmp_path / "rotation.mp4", "rotation")
        result = analyze_shot_motion(video, 0.0, 1.0, 640, 360)

        assert result.status == "ok"
        assert abs(result.rotation_deg) > 1.0
        assert abs(result.rotation_deg) < 5.0

    def test_low_texture_shot(self, tmp_path: Path):
        video = _create_test_video_with_motion(tmp_path / "low_texture.mp4", "low_texture")
        result = analyze_shot_motion(video, 0.0, 1.0, 640, 360)

        assert result.status in {"insufficient_features", "too_few_valid_pairs"}
        assert result.confidence < 0.5


def test_motion_fusion_agrees_with_push_in():
    from schemas.measured_motion import MeasuredMotion

    measured = MeasuredMotion(
        status="ok",
        scale_change_percent=7.2,
        confidence=0.8,
    )
    semantic = {"type": "push_in", "confidence": 0.82}
    summary = fuse_motion(semantic, measured)

    assert summary["semantic_type"] == "push_in"
    assert summary["measured_type"] == "push_in"
    assert summary["conflict"] is False
    assert summary["fused_confidence"] > summary["semantic_confidence"]


def test_motion_fusion_detects_static_scale_conflict():
    from schemas.measured_motion import MeasuredMotion

    measured = MeasuredMotion(
        status="ok",
        scale_change_percent=8.0,
        confidence=0.8,
    )
    semantic = {"type": "static", "confidence": 0.9}
    summary = fuse_motion(semantic, measured)

    assert summary["conflict"] is True
    assert summary["measured_type"] == "push_in"
