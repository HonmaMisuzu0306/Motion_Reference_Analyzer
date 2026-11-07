"""Generate a 2D AE null from a region track computed on the server."""
import json
from math import isfinite
from pathlib import Path
from sys import float_info

from cv.region_track import MAX_DURATION, MAX_SAMPLES, MAX_SOURCE_PIXELS, RegionTrack

_PREFIX_STATUSES = {'no_match', 'ambiguous', 'abrupt_change', 'geometry_changed', 'time_gap'}


def _finite(value):
    # Every finite binary64 number fits in this range, including integral inputs.
    return type(value) in (int, float) and -float_info.max <= value <= float_info.max and isfinite(value)


def _setup(track: RegionTrack, source_start: float, source_end: float, fps: float) -> dict:
    if not isinstance(track, RegionTrack):
        raise ValueError('需要已计算的区域轨迹')
    if not (_finite(source_start) and _finite(source_end) and 0 <= source_start < source_end
            and source_end - source_start <= MAX_DURATION):
        raise ValueError('区域跟踪时间范围无效')
    if not (_finite(fps) and 1 <= fps <= 999):
        raise ValueError('AE 试作要求帧率在 1–999 fps 范围内')
    width, height = track.frame_width, track.frame_height
    if (type(width) is not int or type(height) is not int or not 4 <= width <= 30000
            or not 4 <= height <= 30000 or width * height > MAX_SOURCE_PIXELS):
        raise ValueError('区域跟踪的显示画幅无效')
    if not 2 <= len(track.samples) <= MAX_SAMPLES:
        raise ValueError('至少需要两个已确认的跟踪位置')

    keys = []
    previous = None
    for sample in track.samples:
        t, x, y = sample.source_time, sample.center_x_px, sample.center_y_px
        if not (_finite(t) and source_start <= t < source_end and _finite(x) and 0 <= x <= width
                and _finite(y) and 0 <= y <= height):
            raise ValueError('区域采样时间或位置超出范围')
        if previous is not None and not 0 < t - previous <= .5:
            raise ValueError('区域采样时间不连续或次序无效')
        keys.append([t - track.samples[0].source_time, x, y])
        previous = t

    first, last = track.samples[0].source_time, track.samples[-1].source_time
    if track.status == 'complete' and track.stop_time is None:
        limit = source_end
    elif (track.status in _PREFIX_STATUSES and _finite(track.stop_time)
          and last < track.stop_time < source_end):
        limit = track.stop_time
    else:
        raise ValueError('区域跟踪状态与已确认轨迹不一致')
    return {
        'width': width, 'height': height, 'fps': fps, 'first': first, 'last': last,
        'status': track.status, 'stop': track.stop_time, 'keys': keys,
        'layerEnd': min(limit - first, last - first + 1 / fps),
    }


_SCRIPT = r'''// Motion Reference Analyzer - region position; run in After Effects.
(function () {
    var data = __DATA__;
    if (!app.project) { alert("Please open or create an AE project first."); return; }
    function addComp(fps) {
        // Round the comp up to a whole frame; the null ends at its exact source limit.
        var duration = Math.ceil(data.layerEnd * fps) / fps;
        return app.project.items.addComp("MRA Region Track", data.width, data.height, 1, duration, fps);
    }
    app.beginUndoGroup("MRA region track");
    try {
        var fps = data.fps;
        var comp;
        try { comp = addComp(fps); }
        catch (creationError) {
            if (fps <= 99) { throw creationError; }
            fps = fps / Math.ceil(fps / 99);
            comp = addComp(fps);
        }
        comp.comment = "User-selected image region. Comp 0 s = source " + data.first +
            " s. Last confirmed position at source " + data.last + " s.";
        if (data.stop !== null) {
            comp.comment += " Tracking stopped at source " + data.stop + " s (" + data.status + ").";
        }
        if (fps !== data.fps) {
            comp.comment += " Source " + data.fps + " fps; comp " + fps + " fps. Keys use source seconds.";
        }
        var layer = comp.layers.addNull(comp.duration);
        layer.name = "MRA - tracked region center";
        layer.threeDLayer = false;
        layer.outPoint = data.layerEnd;
        var position = layer.property("ADBE Transform Group").property("ADBE Position");
        position.dimensionsSeparated = true;
        for (var axis = 0; axis < 2; axis++) {
            var prop = position.getSeparationFollower(axis);
            for (var i = 0; i < data.keys.length; i++) {
                var key = data.keys[i];
                prop.setValueAtTime(key[0], key[axis + 1]);
            }
            for (var k = 1; k <= prop.numKeys; k++) {
                prop.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
            }
        }
        comp.openInViewer();
    } catch (error) {
        alert("MRA region track could not be created: " + error.toString() + "\nUndo once to remove this attempt.");
    } finally { app.endUndoGroup(); }
}());
'''


def export_region_ae_script(track: RegionTrack, *, source_start: float, source_end: float, fps: float, path: Path) -> Path:
    setup = _setup(track, source_start, source_end, fps)
    script = _SCRIPT.replace('__DATA__', json.dumps(setup, allow_nan=False, ensure_ascii=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding='utf-8')
    return path
