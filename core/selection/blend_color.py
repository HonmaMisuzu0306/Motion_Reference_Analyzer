"""Compare displayed-channel and sRGB linear-light fits at independent sample points."""
from functools import lru_cache

import numpy as np

_CODES = np.arange(256, dtype=np.float32) / 255
_LINEAR = np.where(_CODES <= .04045, _CODES / 12.92, ((_CODES + .055) / 1.055) ** 2.4)
_ROW, _COL = np.indices((72, 96))
_TRAIN = (_ROW + _COL) % 2 == 0


def color_advice(blend):
    return {
        'srgb_linear': '实测中间帧更接近 sRGB 线性光混合。建议在独立的 sRGB 测试工程中启用「使用 1.0 伽玛混合颜色」，对照原片中间帧。',
        'decoded_rgb': '实测中间帧更接近直接混合解码 RGB 数值。建议在独立的 SDR 测试工程中先用常规混合，对照原片中间帧。',
        'undetermined': '两种颜色混合方式缺少足够区分证据。此表按解码 RGB 数值估算，请对照原片中间帧确认亮度。',
    }.get(blend.get('color_model'), '这条历史曲线按解码 RGB 数值估算。可重新测量以比较颜色混合方式。')


@lru_cache(maxsize=8)
def _indices(height, width):
    # Randomised within each cell once, so regular stripes cannot all fall between samples.
    rng = np.random.default_rng(61985)
    ys = ((_ROW + rng.random(_ROW.shape)) * height / 72).astype(np.intp)
    xs = ((_COL + rng.random(_COL.shape)) * width / 96).astype(np.intp)
    return ys, xs


def sample_codes(image):
    return image[_indices(*image.shape[:2])]


def _score(pictures, lookup, middle, strength, tile_strength):
    first = lookup[pictures[0]]
    delta = lookup[pictures[-1]] - first
    base, axis = first[_TRAIN], delta[_TRAIN]
    variance = np.mean(axis**2)
    if variance < 1e-8:
        return None
    weights = []
    tile_errors = []
    tile_limit = np.maximum(7., .16 * tile_strength)
    valid = True
    for codes, is_middle in zip(pictures, middle):
        weight = np.mean((lookup[codes[_TRAIN]] - base) * axis) / variance
        weights.append(weight)
        prediction = first + weight.clip(0, 1) * delta
        if lookup is _LINEAR:
            prediction = np.where(prediction <= .0031308, 12.92 * prediction,
                                  1.055 * prediction.clip(0, 1) ** (1 / 2.4) - .055)
        error = codes - 255 * prediction
        error[_TRAIN] = 0
        tiles = 2 * np.mean(error.reshape(3, 24, 3, 32, 3)**2, axis=(1, 3, 4))
        if np.any(tiles > tile_limit**2):
            valid = False
        if is_middle:
            tile_errors.append(tiles)
    regional = np.sqrt(np.mean(tile_errors, axis=0))
    score = float(np.sqrt(np.mean(regional**2)))
    weights = np.array(weights)
    interior = weights[(weights > .1) & (weights < .9)]
    valid = (valid and score <= max(3., .09*strength)
             and regional.max() <= max(6., .16*strength)
             and np.max(np.maximum.accumulate(weights) - weights) <= .025
             and len(np.unique(np.floor(interior*10))) >= 4)
    return score, regional, weights, valid


def compare_models(pictures, phase, strength, tile_strength):
    middle = (phase > .15) & (phase < .85)
    if np.count_nonzero(middle) < 4:
        return None
    scores = {}
    for name, lookup in [('decoded_rgb', _CODES), ('srgb_linear', _LINEAR)]:
        fit = _score(pictures, lookup, middle, strength, tile_strength)
        if fit is None:
            return None
        scores[name] = fit
    winner, other = sorted(scores, key=lambda name: scores[name][0])
    score, regional, weights, valid = scores[winner]
    alternate, comparison, _, _ = scores[other]
    votes = np.count_nonzero((comparison-regional > 1.) & (regional < .85*comparison))
    if not (valid and alternate-score > 1.3 and score < .8*alternate and votes >= 7):
        return None
    return winner, weights, {name: round(item[0], 2) for name, item in scores.items()}
