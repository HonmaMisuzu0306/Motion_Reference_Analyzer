"""Export a self-contained, reversible AE prototype from qualified motion curves.

The script creates its own compositions. It never opens media, executes input text,
changes selected layers, saves the user's project, or launches After Effects.
"""
import json
from math import isfinite
from pathlib import Path

from recipe.ae_recipe import generate_ae_recipe


def _ae_value(property_name: str, value: float, width: int, height: int) -> float:
    if property_name == 'position_x':
        return width / 2 + (value / 100) * width
    if property_name == 'position_y':
        return height / 2 + (value / 100) * height
    if property_name in {'global_scale', 'rotation'}:
        return value
    raise ValueError('不支持的 AE 动画属性')


def build_ae_setup(shot: dict, *, width: int, height: int, fps: float, padded: bool = False) -> dict:
    """Validate once before producing any file or AE project item."""
    if (isinstance(width, bool) or isinstance(height, bool)
            or not isinstance(width, int) or not isinstance(height, int)
            or not 4 <= width <= 30000 or not 4 <= height <= 30000):
        raise ValueError('AE 合成尺寸须为 4–30000 像素，请检查视频元数据')
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not 1 <= fps <= 999 or not isfinite(fps):
        raise ValueError('AE 试作脚本要求原视频帧率在 1–999 fps 范围内')
    # Recompute from evidence; stale or edited cached recipes are not executable input.
    recipe = generate_ae_recipe(shot)
    plan = recipe.get('animation_plan') or {}
    curves = plan.get('curves') or []
    if plan.get('evidence_source') != 'measured' or not curves:
        raise ValueError('需要可靠、连续且有变化的实测轨迹；请重新分析，或使用文字建议手动试作')
    duration = plan.get('duration')
    if duration is None or not isfinite(duration) or not 1 / fps <= duration <= 10800:
        raise ValueError('AE 合成时长须至少一帧且不超过 3 小时')
    if (shot.get('measured_motion') or {}).get('frame_width') != width or (
            shot.get('measured_motion') or {}).get('frame_height') != height:
        raise ValueError('轨迹尺寸与视频元数据不一致，请重新分析')
    for curve in curves:
        points = curve['points']
        if len(points) < 2 or any(not 0 <= p['time'] < duration or not isfinite(p['value']) for p in points):
            raise ValueError('轨迹关键帧无效，请重新分析')
        if any(b['time'] <= a['time'] for a, b in zip(points, points[1:])):
            raise ValueError('轨迹时间必须严格递增')
        if any(not isfinite(_ae_value(curve['property'], point['value'], width, height)) for point in points):
            raise ValueError('轨迹换算为 AE 单位后超出有限数值范围，请重新分析')
    padding = plan.get('artwork_padding') if padded else None
    if padded and (not padding or (padding['width_px'], padding['height_px']) == (width, height)):
        raise ValueError('当前曲线无需留边或无法估算留边，请使用普通试作脚本')
    return {'artwork_padding': padding, 'version': 'ae-setup-v1', 'name': 'MRA ' + str(shot.get('shot_id', 'shot'))[:100],
            'width': width, 'height': height, 'fps': float(fps), 'duration': duration,
            'source_start': plan['source_start'], 'source_end': plan['source_end'],
            'coverage_start': plan['coverage_start'] - plan['source_start'],
            'coverage_end': plan['coverage_end'] - plan['source_start'],
            'curves': curves, 'notes': ([plan['evidence_notice']] if plan.get('evidence_notice') else []) + plan.get('notes', [])}


# ES3-compatible ExtendScript; match names work regardless of AE's UI language.
# Separate X/Y properties avoid AE's default spatial Bezier interpolation and
# allow each independently simplified channel to keep its exact sample times.
_SCRIPT = r'''// Motion Reference Analyzer — measured motion prototype
// Run with File > Scripts > Run Script File in After Effects.
// Replace the contents of the new CONTENT comp with a still / static artwork.
// Do not put an already-moving reference video there (that doubles its motion).
// Linear interpolation approximates samples; it does not recover original easing.
(function () {
    var data = __MRA_DATA__;
    if (!app.project) { alert("Please open or create an AE project first."); return; }
    var padding = data.artwork_padding || {left_px: 0, top_px: 0, width_px: data.width, height_px: data.height};
    function addContent(fps) {
        return app.project.items.addComp(data.name + " CONTENT", padding.width_px, padding.height_px, 1, data.duration, fps);
    }
    app.beginUndoGroup("MRA motion prototype");
    try {
        var folder = app.project.items.addFolder(data.name);
        var previewFps = data.fps;
        var content;
        try {
            content = addContent(previewFps);
        } catch (creationError) {
            // Older AE scripting hosts cap addComp at 99 fps. Keep real seconds
            // and use an integer divisor so preview frames stay on the source grid.
            if (data.fps <= 99) { throw creationError; }
            previewFps = data.fps / Math.ceil(data.fps / 99);
            if (data.duration < 1 / previewFps) { throw creationError; }
            content = addContent(previewFps);
        }
        content.parentFolder = folder;
        content.comment = "Replace these static calibration marks with static artwork of the same dimensions. Keep the outer layer unparented and 2D.";
        if (data.artwork_padding) {
            content.comment += " Original picture starts at (" + padding.left_px + ", " + padding.top_px +
                ") in this enlarged canvas. Extend static artwork into the margins.";
        }
        // Small static asymmetric marks make both rotation and translation visible.
        var colors = [[0.18, 0.62, 0.94], [0.97, 0.72, 0.22], [0.91, 0.32, 0.44]];
        var locations = [[0.35, 0.5], [0.65, 0.35], [0.65, 0.65]];
        for (var m = 0; m < colors.length; m++) {
            var mark = content.layers.addSolid(colors[m], "Static mark " + (m + 1),
                Math.max(4, Math.round(data.width * (m === 0 ? 0.18 : 0.08))),
                Math.max(4, Math.round(data.height * (m === 0 ? 0.24 : 0.12))), 1, data.duration);
            mark.property("ADBE Transform Group").property("ADBE Position").setValue(
                [padding.left_px + data.width * locations[m][0], padding.top_px + data.height * locations[m][1]]);
        }
        var comp = app.project.items.addComp(data.name + " MOTION", data.width, data.height, 1, data.duration, previewFps);
        comp.parentFolder = folder;
        comp.bgColor = [0.035, 0.045, 0.065];
        comp.comment = "Source range [" + data.source_start + ", " + data.source_end + ") sec. Local measured coverage [" + data.coverage_start + ", " + data.coverage_end + "] sec. Outside coverage AE holds the endpoint; this is not measured evidence.\n" + data.notes.join("\n");
        if (previewFps !== data.fps) {
            comp.comment += "\nSource " + data.fps + " fps; this AE host previews at " + previewFps + " fps. Keyframe times remain in source seconds.";
        }
        var layer = comp.layers.add(content);
        layer.name = "MRA measured motion - replace CONTENT artwork";
        layer.threeDLayer = false;
        var transform = layer.property("ADBE Transform Group");
        transform.property("ADBE Anchor Point").setValue([padding.left_px + data.width / 2, padding.top_px + data.height / 2]);
        var position = transform.property("ADBE Position");
        position.setValue([data.width / 2, data.height / 2]);
        position.dimensionsSeparated = true;
        transform.property("ADBE Scale").setValue([100, 100]);
        transform.property("ADBE Rotate Z").setValue(0);
        for (var c = 0; c < data.curves.length; c++) {
            var curve = data.curves[c];
            var prop;
            if (curve.property === "position_x") { prop = position.getSeparationFollower(0); }
            else if (curve.property === "position_y") { prop = position.getSeparationFollower(1); }
            else if (curve.property === "global_scale") { prop = transform.property("ADBE Scale"); }
            else if (curve.property === "rotation") { prop = transform.property("ADBE Rotate Z"); }
            else { throw new Error("Unsupported motion property"); }
            for (var p = 0; p < curve.points.length; p++) {
                var point = curve.points[p];
                var value = point.value;
                // Divide before multiplying, to avoid overflowing a finite offset.
                if (curve.property === "position_x") { value = data.width / 2 + (value / 100) * data.width; }
                else if (curve.property === "position_y") { value = data.height / 2 + (value / 100) * data.height; }
                else if (curve.property === "global_scale") { value = [value, value]; }
                var dimensions = value instanceof Array ? value : [value];
                for (var d = 0; d < dimensions.length; d++) {
                    if (!isFinite(dimensions[d]) || (prop.hasMin && dimensions[d] < prop.minValue)
                            || (prop.hasMax && dimensions[d] > prop.maxValue)) {
                        throw new Error("Motion value is outside this AE property's supported range");
                    }
                }
                prop.setValueAtTime(point.time, value);
            }
            for (var k = 1; k <= prop.numKeys; k++) {
                prop.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
            }
        }
        comp.workAreaStart = data.coverage_start;
        // Work-area duration is end-exclusive; include the last measured frame.
        comp.workAreaDuration = Math.min(data.duration - data.coverage_start,
            data.coverage_end - data.coverage_start + 1 / previewFps);
        comp.time = data.coverage_start;
        comp.openInViewer();
    } catch (error) {
        alert("MRA prototype could not be completed: " + error.toString() + "\nUndo once to remove this attempt.");
    } finally {
        app.endUndoGroup();
    }
}());
'''


def render_ae_script(setup: dict) -> str:
    # ASCII JSON escapes quotes, backslashes, Unicode line breaks and all user text.
    return _SCRIPT.replace('__MRA_DATA__', json.dumps(setup, ensure_ascii=True, allow_nan=False))


def export_ae_script(shot: dict, *, width: int, height: int, fps: float, path: Path, padded: bool = False) -> Path:
    setup = build_ae_setup(shot, width=width, height=height, fps=fps, padded=padded)
    content = render_ae_script(setup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path
