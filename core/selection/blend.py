"""Measure a full-frame blend between two held pictures within a user selection."""
import cv2
import numpy as np

from selection.blend_color import color_advice, compare_models, sample_codes

METHOD = 'two-held-pictures-v3'
MAX_SECONDS = 6
MAX_FRAMES = 360


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values))))


def _tile_rms(image):
    tiles = image.reshape(3, 12, 3, 16, 3)
    return np.sqrt(np.mean(tiles ** 2, axis=(1, 3, 4)))


def _distributed_residual(error, limit, minimum_tiles):
    return _rms(error) > limit and np.count_nonzero(_tile_rms(error) > limit) >= minimum_tiles


def _distinct_pictures(first, last, delta_rms):
    for picture in (first, last):
        if np.max(np.std(picture, axis=(0, 1))) < 15:
            return False
    # Exposure, tint, and channel mixing of one image also fit a two-endpoint blend.
    pixels = first.reshape(-1, 3)
    design = np.column_stack((pixels, np.ones(len(pixels))))
    target = last.reshape(-1, 3)
    color_fit = design @ np.linalg.lstsq(design, target, rcond=None)[0]
    # On a dark-to-bright cut the mean color can change much more than either
    # picture's texture. Compare the unexplained detail to the smaller scale.
    texture = _rms(last - last.mean(axis=(0, 1)))
    threshold = max(6, min(.20 * delta_rms, .35 * texture))
    if not _distributed_residual((target - color_fit).reshape(last.shape), threshold, 6):
        return False
    # A gamma or contrast curve can be nonlinear even on a completely still image.
    by_level = np.empty_like(target)
    for channel in range(3):
        bins = pixels[:, channel].astype(np.intp) // 8
        counts = np.bincount(bins, minlength=32)
        sums = np.bincount(bins, weights=target[:, channel], minlength=32)
        by_level[:, channel] = (sums / np.maximum(1, counts))[bins]
    if not _distributed_residual((target - by_level).reshape(last.shape), threshold, 6):
        return False
    # A vignette or spotlight changes many tiles, but preserves the local detail
    # of a still. Check the detail after removing slowly varying illumination.
    detail_a = (first - cv2.GaussianBlur(first, (0, 0), 1.8)).reshape(-1, 3)
    detail_b = (last - cv2.GaussianBlur(last, (0, 0), 1.8)).reshape(-1, 3)
    predicted = detail_a @ np.linalg.lstsq(detail_a, detail_b, rcond=None)[0]
    residual = (detail_b - predicted).reshape(last.shape)
    return _distributed_residual(residual, max(3., .35 * _rms(detail_b)), 5)


def _held(frames, times, duration):
    stop = int(np.searchsorted(times - times[0], .12))
    if stop >= len(frames) or stop < 2 or times[stop] - times[0] > duration / 3:
        return False
    return all(_rms(picture - frames[0]) <= 1.65 for picture in frames[1:stop + 1])


def _linear_keys(times, opacity, selection_end):
    """Keep source PTS at which a straight line misses a measured value by >1 point."""
    keep = {0, len(times) - 1}
    intervals = [(0, len(times) - 1)]
    while intervals:
        start, end = intervals.pop()
        if end <= start + 1:
            continue
        between = times[start + 1:end]
        linear = np.interp(between, times[[start, end]], opacity[[start, end]])
        errors = np.abs(opacity[start + 1:end] - linear)
        worst = int(np.argmax(errors))
        if errors[worst] > 1:
            middle = start + 1 + worst
            keep.add(middle)
            intervals.extend(((start, middle), (middle, end)))
    keys = []
    for i in sorted(keep):
        key = {'source_time': float(times[i]), 'opacity_percent': float(opacity[i])}
        # An exclusive bound lets a video player seek inside the decoded picture.
        end = times[i + 1] if i + 1 < len(times) else selection_end
        if end is not None and end > times[i]:
            key['frame_end'] = float(end)
        keys.append(key)
    return keys


def _recipe(times, weights, selection_end, model):
    opacity = np.round(np.clip(weights.astype(float), 0, 1) * 100, 1)
    result = {'method': METHOD, 'sample_count': len(times), 'color_model': 'undetermined',
              'keyframes': _linear_keys(times, opacity, selection_end)}
    if model:
        result.update(color_model=model[0], model_rms=model[2])
    result['color_advice'] = color_advice(result)
    return result


def _continuous_boundary(times, weights, boundary):
    # A bright first linear-light blend step may resemble a cut in display RGB.
    # Require a small step supported by the measured speed on at least one side
    # (the other side may be a hold). Compare on the source clock for VFR.
    i = int(np.searchsorted(times, boundary))
    if i == 0 or i >= len(times) or times[i] != boundary:
        return False
    steps = np.diff(weights)
    if np.max(np.abs(steps)) > .09:
        return False
    intervals = np.diff(times)
    speed = steps / intervals
    j = i - 1
    step = steps[j]
    if step <= .005:
        return False
    for neighbor in (speed[max(0, j-3):j], speed[j+1:j+4]):
        if len(neighbor) >= 2:
            expected = neighbor * intervals[j]
            if np.count_nonzero(np.abs(step-expected) <= max(.004, .3*step)) >= 2:
                return True
    return False


class BlendSamples:
    def __init__(self):
        self.times = []
        self.pictures = []
        self.color_samples = []
        self.skip_message = ''

    def add(self, time, image):
        if self.skip_message:
            return
        if len(self.times) >= MAX_FRAMES:
            self.skip_message = f'选区超过 {MAX_FRAMES} 帧，请缩短到一次过渡并保留两端的静止画面。'
        elif self.times and not 0 < time - self.times[-1] <= .125001:
            self.skip_message = '选区内的帧时间有缺口，无法可靠估算连续的不透明度。'
        if self.skip_message:
            self.pictures.clear()
            self.color_samples.clear()
            return
        self.times.append(time)
        self.pictures.append(cv2.resize(image, (48, 36), interpolation=cv2.INTER_AREA))
        if image.shape[0] >= 72 and image.shape[1] >= 96:
            self.color_samples.append(sample_codes(image))

    def estimate(self, selection_end=None, *, boundary=None):
        if self.skip_message or len(self.times) < 9:
            return None
        times = np.array(self.times)
        frames = np.array(self.pictures, dtype=np.float32)
        duration = times[-1] - times[0]
        first, last = frames[0], frames[-1]
        delta = last - first
        strength = _rms(delta)
        # Require changes across the frame, instead of a changing logo or caption.
        tile_strength = _tile_rms(delta)
        if strength < 12 or np.count_nonzero(tile_strength >= max(10, .40 * strength)) < 7:
            return None
        if not _held(frames, times, duration) or not _held(frames[::-1], -times[::-1], duration):
            return None
        if not _distinct_pictures(first, last, strength):
            return None

        weights = np.mean((frames - first) * delta, axis=(1, 2, 3)) / np.mean(delta ** 2)
        # Avoid using a pixel for both fitting and validation on very small rasters.
        model = (compare_models(self.color_samples, weights, strength, tile_strength)
                 if len(self.color_samples) == len(times) else None)
        if boundary is not None and not (model and model[0] == 'srgb_linear'
                                         and _continuous_boundary(times, model[1], boundary)):
            return None
        if model and model[0] == 'srgb_linear':
            return _recipe(times, model[1], selection_end, model)
        # Compare to the highest previous weight to detect gradual reversals too.
        if np.max(np.maximum.accumulate(weights) - weights) > .025:
            return None
        interior = weights[(weights > .1) & (weights < .9)]
        if len(np.unique(np.floor(interior * 10))) < 4:
            return None
        for frame, weight in zip(frames, weights):
            error = frame - first - weight * delta
            if _rms(error) > .09 * strength or np.any(_tile_rms(error) > np.maximum(4, .16 * tile_strength)):
                return None
        return _recipe(times, weights, selection_end, model)
