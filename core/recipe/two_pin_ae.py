"""Export a server-computed two-pin similarity transform into a fresh AE composition."""
import json
from math import cos, hypot, isclose, radians, sin
from pathlib import Path
from sys import float_info

from cv.region_track import MAX_DURATION, MAX_SAMPLES, MAX_SOURCE_PIXELS
from cv.two_pin import MAX_STEP_DEGREES, TwoPinSample, TwoPinTrack, minimum_baseline_px

_PREFIX_STATUSES = {'pin_lost', 'time_mismatch', 'time_gap', 'degenerate', 'angle_jump'}


def _finite(value):
    return type(value) in (int, float) and -float_info.max <= value <= float_info.max


def _setup(track: TwoPinTrack, source_start: float, source_end: float, fps: float) -> dict:
    if not isinstance(track, TwoPinTrack):
        raise ValueError('需要从两个已确认的区域轨迹计算姿态')
    if not (_finite(source_start) and _finite(source_end) and 0 <= source_start < source_end
            and source_end - source_start <= MAX_DURATION and _finite(fps) and 1 <= fps <= 999):
        raise ValueError('双点试作的源片时间或帧率无效')
    width, height = track.frame_width, track.frame_height
    if (type(width) is not int or type(height) is not int or not 4 <= width <= 30000
            or not 4 <= height <= 30000 or width * height > MAX_SOURCE_PIXELS):
        raise ValueError('双点试作的显示画幅无效')
    if (not isinstance(track.samples, list) or not 2 <= len(track.samples) <= MAX_SAMPLES
            or any(not isinstance(p, TwoPinSample) for p in track.samples)):
        raise ValueError('至少需要两组同步且已确认的双点位置')
    dx, dy, distance = track.initial_vector_x_px, track.initial_vector_y_px, track.initial_distance_px
    minimum_separation = minimum_baseline_px(width, height)
    if not (all(_finite(v) for v in (dx, dy, distance)) and distance >= minimum_separation
            and isclose(hypot(dx, dy), distance, abs_tol=1e-7, rel_tol=1e-9)):
        raise ValueError('初始双点向量与距离不一致')
    keys = []
    first = track.samples[0].source_time
    previous = None
    for p in track.samples:
        t, ax, ay = p.source_time, p.position_x_px, p.position_y_px
        bx, by = p.pin_b_x_px, p.pin_b_y_px
        rotation, scale = p.rotation_deg, p.scale_percent
        if not (all(_finite(v) for v in (t, ax, ay, bx, by, rotation, scale))
                and source_start <= t < source_end and 0 <= ax < width and 0 <= bx < width
                and 0 <= ay < height and 0 <= by < height and scale > 0
                and hypot(bx - ax, by - ay) >= minimum_separation):
            raise ValueError('双点采样超出时间或画幅范围')
        if previous is None:
            if abs(rotation) > 1e-7 or abs(scale - 100) > 1e-7:
                raise ValueError('首个双点姿态必须为原始角度和大小')
        elif not (0 < t - previous.source_time <= .5
                  and abs(rotation - previous.rotation_deg) <= MAX_STEP_DEGREES + 1e-8):
            raise ValueError('双点姿态的时间或旋转不连续')
        angle = radians(rotation)
        predicted_x = ax + (dx * cos(angle) - dy * sin(angle)) * (scale / 100)
        predicted_y = ay + (dx * sin(angle) + dy * cos(angle)) * (scale / 100)
        if hypot(predicted_x - bx, predicted_y - by) > 1e-5:
            raise ValueError('姿态不能复现第二个实测点')
        keys.append([t - first, ax, ay, rotation, scale])
        previous = p
    last = track.samples[-1].source_time
    both_complete = track.pin_a_status == track.pin_b_status == 'complete'
    if track.status == 'complete' and track.stop_time is None and both_complete:
        limit = source_end
    elif (track.status in _PREFIX_STATUSES and not (track.status == 'pin_lost' and both_complete)
          and _finite(track.stop_time) and last < track.stop_time < source_end):
        limit = track.stop_time
    else:
        raise ValueError('停止状态与双点轨迹范围不一致')
    return {'width': width, 'height': height, 'keys': keys, 'offset': [dx, dy], 'fps': fps,
            'first': first, 'last': last, 'stop': track.stop_time, 'status': track.status,
            'layerEnd': min(limit - first, last - first + 1 / fps)}


_SCRIPT = r'''// Motion Reference Analyzer - tracked two-pin layer pose.
// A and B are two marks selected on the same moving plane.
(function () {
    var data = __DATA__;
    if (!app.project) { alert("Please open or create an AE project first."); return; }
    function addComp(fps) {
        var duration = Math.ceil(data.layerEnd * fps) / fps;
        return app.project.items.addComp("MRA Two-Pin Pose", data.width, data.height, 1, duration, fps);
    }
    function addNull(comp, name) {
        var layer = comp.layers.addNull(comp.duration);
        layer.name = name;
        layer.threeDLayer = false;
        layer.outPoint = data.layerEnd;
        return layer;
    }
    function makeLinear(prop) {
        for (var k = 1; k <= prop.numKeys; k++) {
            prop.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
        }
    }
    app.beginUndoGroup("MRA two-pin layer pose");
    try {
        var fps = data.fps, comp;
        try { comp = addComp(fps); }
        catch (e) {
            if (fps <= 99) { throw e; }
            fps = fps / Math.ceil(fps / 99);
            comp = addComp(fps);
        }
        comp.comment = "Two visible marks on a user-selected plane. Comp zero = source " + data.first +
            " s. Last confirmed pair at source " + data.last + " s. Linear interpolation between observations.";
        if (data.stop !== null) { comp.comment += " Tracking stopped at " + data.stop + " s (" + data.status + ")."; }
        if (fps !== data.fps) { comp.comment += " Source " + data.fps + " fps; comp " + fps + " fps."; }
        var root = addNull(comp, "A - tracked layer pose");
        var marker = addNull(comp, "B - second mark");
        var transform = root.property("ADBE Transform Group");
        transform.property("ADBE Anchor Point").setValue([0, 0]);
        // AE may compensate transforms when assigning a parent; set all child-local properties afterwards.
        marker.parent = root;
        var local = marker.property("ADBE Transform Group");
        local.property("ADBE Anchor Point").setValue([0, 0]);
        local.property("ADBE Position").setValue(data.offset);
        local.property("ADBE Scale").setValue([100, 100]);
        local.property("ADBE Rotate Z").setValue(0);
        var position = transform.property("ADBE Position");
        position.dimensionsSeparated = true;
        var x = position.getSeparationFollower(0), y = position.getSeparationFollower(1);
        var rotation = transform.property("ADBE Rotate Z"), scale = transform.property("ADBE Scale");
        for (var i = 0; i < data.keys.length; i++) {
            var p = data.keys[i];
            x.setValueAtTime(p[0], p[1]); y.setValueAtTime(p[0], p[2]);
            rotation.setValueAtTime(p[0], p[3]); scale.setValueAtTime(p[0], [p[4], p[4]]);
        }
        makeLinear(x); makeLinear(y); makeLinear(rotation); makeLinear(scale);
        comp.openInViewer();
    } catch (error) {
        alert("MRA two-pin pose could not be created: " + error.toString() + "\nUndo once to remove this attempt.");
    } finally { app.endUndoGroup(); }
}());
'''


def export_two_pin_ae_script(track: TwoPinTrack, *, source_start: float, source_end: float, fps: float, path: Path) -> Path:
    """Validate trusted analysis results before opening an output file."""
    setup = _setup(track, source_start, source_end, fps)
    script = _SCRIPT.replace('__DATA__', json.dumps(setup, ensure_ascii=True, allow_nan=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding='utf8')
    return path
