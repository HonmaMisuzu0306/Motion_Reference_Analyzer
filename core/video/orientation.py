"""Normalize a track's orthogonal display transform to top-left-origin BGR pixels."""
import struct
from functools import lru_cache

import cv2
import numpy as np

# AVDisplayMatrix maps row vectors: x' = a*x + c*y, y' = b*x + d*y.
# Each nonzero coefficient below is one in native-endian 16.16 fixed point.
# The value is (transpose axes, reverse output columns, reverse output rows).
_TRANSFORMS = {
    (1, 0, 0, 1): (False, False, False),
    (-1, 0, 0, 1): (False, True, False),
    (1, 0, 0, -1): (False, False, True),
    (-1, 0, 0, -1): (False, True, True),
    (0, 1, 1, 0): (True, False, False),
    (0, -1, 1, 0): (True, False, True),
    (0, 1, -1, 0): (True, True, False),
    (0, -1, -1, 0): (True, True, True),
}
_IDENTITY = _TRANSFORMS[(1, 0, 0, 1)]
# Bound the extra square-pixel raster allocated for anamorphic media. A bogus
# but syntactically valid SAR can otherwise request billions of output pixels.
_MAX_SAR_PIXELS = 8192 * 4320
_MAX_SAR_EDGE = 30000


@lru_cache(maxsize=32)
def _transform(matrix: bytes | None) -> tuple[bool, bool, bool]:
    if matrix is None:
        return _IDENTITY
    if len(matrix) != 36:
        raise ValueError('视频显示矩阵数据不完整')
    a, b, u, c, d, v, _, _, w = struct.unpack('=9i', matrix)
    # A track-origin translation cancels when re-basing the entire upright
    # picture to its bounding rectangle. Perspective/scale/shear do not.
    if (u, v, w) == (0, 0, 1 << 30):
        for axes, operation in _TRANSFORMS.items():
            if (a, b, c, d) == tuple(value * 65536 for value in axes):
                return operation
    raise ValueError('视频含不支持的显示矩阵，仅支持 90° 整数倍旋转与镜像。请先将显示方向烘焙到画面后重新导入。')


def stream_display_matrix(stream) -> bytes | None:
    context = getattr(stream, 'codec_context', None)
    return getattr(context, 'coded_side_data', {}).get('display_matrix')


def _square_pixel_width(width: int, height: int, sar) -> int:
    # FFmpeg uses zero or an absent SAR for an unspecified pixel shape.
    if sar is None or sar == 0 or sar == 1:
        return width
    n, d = sar.numerator, sar.denominator
    if n <= 0 or d <= 0:
        raise ValueError('视频像素宽高比无效，请检查文件或转码为方形像素。')
    # Round the display width once, half-up, with integer arithmetic.
    normalized = (2 * width * n + d) // (2 * d)
    if (normalized < 1 or max(normalized, height) > _MAX_SAR_EDGE
            or normalized * height > _MAX_SAR_PIXELS):
        raise ValueError('像素宽高比换算后的画幅超出支持范围，请先转码为方形像素。')
    return normalized


def display_dimensions(stream) -> tuple[int, int]:
    width, height = stream.codec_context.width, stream.codec_context.height
    width = _square_pixel_width(width, height, getattr(stream, 'sample_aspect_ratio', None))
    transpose, _, _ = _transform(stream_display_matrix(stream))
    return (height, width) if transpose else (width, height)


def display_bgr(frame, stream) -> np.ndarray:
    """Apply orientation once. A conflicting per-frame orientation is unsupported."""
    operation = _transform(stream_display_matrix(stream))
    side = getattr(frame, 'side_data', {}).get('DISPLAYMATRIX')
    if side is not None and _transform(bytes(side)) != operation:
        raise ValueError('帧显示方向与视频轨道不一致。请先将逐帧方向烘焙到画面后重新导入。')
    sar = getattr(stream, 'sample_aspect_ratio', None)
    target_width = None
    if sar is not None and sar not in (0, 1):
        width, height = stream.codec_context.width, stream.codec_context.height
        target_width = _square_pixel_width(width, height, sar)
    pixels = frame.to_ndarray(format='bgr24')
    if target_width is not None:
        if pixels.shape[:2] != (height, width):
            raise ValueError('视频帧尺寸与轨道不一致，请先转码为固定画幅。')
        if target_width != width:
            interpolation = cv2.INTER_LINEAR if target_width > width else cv2.INTER_AREA
            pixels = cv2.resize(pixels, (target_width, height), interpolation=interpolation)
    transpose, flip_x, flip_y = operation
    if transpose:
        pixels = pixels.swapaxes(0, 1)
    if flip_x:
        pixels = pixels[:, ::-1]
    if flip_y:
        pixels = pixels[::-1]
    return np.ascontiguousarray(pixels)
