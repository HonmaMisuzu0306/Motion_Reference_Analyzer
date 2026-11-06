"""Portable AE blend comp using the two measured pictures and their source clock."""
import hashlib
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import sleep
from zipfile import ZIP_DEFLATED, ZipFile

import av
import cv2

from cv.frame_sampler import _check_stream_pixels
from cv.region_track import MAX_DECODED_FRAMES, MAX_SOURCE_PIXELS
from selection.blend import MAX_FRAMES, MAX_SECONDS
from selection.blend_color import color_advice
from video.orientation import display_bgr
from video.playback_file import (
    PlaybackSourceChanged,
    check_key,
    file_key,
    open_media,
    verified_digest,
)
from video.timing import relative_frame_time, video_origin

_SCRIPT = r'''// Unzip the entire package before running this file in After Effects.
(function () {
    var data = __DATA__;
    if (!app.project) { alert("Open or create a project, then run this script again."); return; }
    var dir = new File($.fileName).parent;
    var firstFile = new File(dir.fsName + "/start.png");
    var lastFile = new File(dir.fsName + "/end.png");
    var referenceFile = new File(dir.fsName + "/reference.png");
    if (!firstFile.exists || !lastFile.exists || (data.reference && !referenceFile.exists)) {
        alert("Extract all the PNG files next to this script."); return;
    }
    function addComp(fps) {
        var frames = Math.max(1, Math.ceil(data.duration * fps - 1e-8));
        return app.project.items.addComp("MRA - opacity blend", data.width, data.height, 1, frames / fps, fps);
    }
    function importStill(file, folder) {
        var options = new ImportOptions(file);
        options.sequence = false;
        var footage = app.project.importFile(options);
        // display_bgr baked the source's display orientation and PAR into the PNG.
        footage.pixelAspect = 1;
        footage.parentFolder = folder;
        return footage;
    }
    function imageLayer(footage, name, comp, duration) {
        var layer = comp.layers.add(footage);
        layer.name = name;
        layer.startTime = 0;
        layer.inPoint = 0;
        layer.outPoint = duration;
        layer.blendingMode = BlendingMode.NORMAL;
        return layer;
    }
    function opacityOf(layer) {
        return layer.property("ADBE Transform Group").property("ADBE Opacity");
    }
    app.beginUndoGroup("MRA opacity blend");
    try {
        var fps = data.fps;
        var comp;
        try { comp = addComp(fps); }
        catch (e) {
            if (fps <= 99) { throw e; }
            fps = fps / Math.ceil(fps / 99);
            comp = addComp(fps);
        }
        var folder = app.project.items.addFolder("MRA - blend plates");
        comp.parentFolder = folder;
        comp.displayStartTime = 0;
        comp.comment = "Comp 0 s = source " + data.sourceStart + " s. Measured from source " + data.hash + ".";
        if (fps !== data.fps) {
            comp.comment += " Source " + data.fps + " fps; comp " + fps + " fps. Keys use source seconds.";
        }
        var first = importStill(firstFile, folder);
        var last = importStill(lastFile, folder);
        opacityOf(imageLayer(first, "Start - bottom", comp, data.duration)).setValue(100);
        var opacity = opacityOf(imageLayer(last, "End - top", comp, data.duration));
        for (var i = 0; i < data.keys.length; i++) {
            opacity.setValueAtTime(data.keys[i][0], data.keys[i][1]);
            opacity.setInterpolationTypeAtKey(i + 1, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
        }
        if (data.reference) {
            var ref = data.reference;
            var duration = 1 / fps;
            var check = app.project.items.addComp("MRA - compare source frame", data.width, data.height, 1, duration, fps);
            check.parentFolder = folder;
            check.displayStartTime = 0;
            check.comment = "Source " + ref.sourceTime + " s. Snapshot of exported blend at " + ref.opacity + "%.";
            opacityOf(imageLayer(first, "Start", check, duration)).setValue(100);
            opacityOf(imageLayer(last, "End - measured opacity", check, duration)).setValue(ref.opacity);
            var original = imageLayer(importStill(referenceFile, folder), "Source - Difference (solo for original)", check, duration);
            original.blendingMode = BlendingMode.DIFFERENCE;
        }
        comp.openInViewer();
    } catch (error) {
        alert("MRA could not finish: " + error.toString() + "\nUndo once to remove this attempt.");
    } finally { app.endUndoGroup(); }
}());
'''


def _number(value):
    return type(value) in (float, int) and math.isfinite(value)


def _plan(record):
    result = record.get('result')
    blend = result.get('opacity_blend') if isinstance(result, dict) else None
    if not isinstance(blend, dict):
        raise ValueError('记录缺少可导出的叠化曲线')
    keys = blend.get('keyframes')
    if (record['kind'] != 'clip' or record['status'] not in ('done', 'completed_with_warnings')
            or blend.get('method') not in ('two-held-pictures-v1', 'two-held-pictures-v2', 'two-held-pictures-v3')
            or not isinstance(keys, list) or not 2 <= len(keys) <= MAX_FRAMES):
        raise ValueError('请选择已测得叠化曲线的片段记录')
    selection = result.get('time')
    if not isinstance(selection, dict):
        raise ValueError('记录缺少选区时间')
    start, end = selection.get('start'), selection.get('end')
    if not (_number(start) and _number(end) and 0 <= start < end and end - start <= MAX_SECONDS):
        raise ValueError('记录的选区范围无效')
    points, times = [], []
    for key in keys:
        if not isinstance(key, dict):
            raise ValueError('叠化关键帧数据无效')
        t, opacity = key.get('source_time'), key.get('opacity_percent')
        if not (_number(t) and start <= t < end and _number(opacity) and 0 <= opacity <= 100):
            raise ValueError('叠化关键帧越出选区或不透明度范围')
        if times and t <= times[-1]:
            raise ValueError('叠化关键帧时间次序无效')
        points.append([t - start, opacity])
        times.append(t)
    if points[0][1] != 0 or points[-1][1] != 100:
        raise ValueError('叠化首尾参考画面不完整')
    return {'sourceStart': start, 'duration': end - start, 'keys': points, 'hash': record['source_hash']}, times


def _write_png(archive, name, frame, stream, data):
    image = display_bgr(frame, stream)
    h, w = image.shape[:2]
    if not (4 <= w <= 30000 and 4 <= h <= 30000 and w*h <= MAX_SOURCE_PIXELS):
        raise ValueError('参考画幅超出 AE 合成范围')
    if name == 'start.png':
        data.update(width=w, height=h)
    elif (w, h) != (data['width'], data['height']):
        raise ValueError('参考画面的尺寸不同')
    ok, png = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('无法生成参考 PNG')
    archive.writestr(name, png.tobytes())


def _write_pictures(file, times, archive, data):
    with av.open(file) as media:
        stream = media.streams.video[0]
        _check_stream_pixels(stream, MAX_SOURCE_PIXELS)
        fps = float(stream.average_rate or 0)
        if not math.isfinite(fps) or fps < 1:
            raise ValueError('素材帧率不适用于 AE 合成')
        data['fps'] = fps
        first, last = times[0], times[-1]
        media.seek(math.floor((video_origin(stream) + first) / stream.time_base), stream=stream, backward=True)
        index, reference, nearest = 0, None, 40.
        for count, frame in enumerate(media.decode(stream), 1):
            if count > MAX_DECODED_FRAMES:
                break
            time = relative_frame_time(stream, frame.pts, frame.time_base)
            if index and times[index-1] < time <= times[index] and time < last:
                left, right = data['keys'][index-1][1], data['keys'][index][1]
                fraction = (time-times[index-1]) / (times[index]-times[index-1])
                opacity = left + fraction*(right-left)
                if abs(opacity-50) < nearest:
                    nearest = abs(opacity-50)
                    reference = frame
                    data['reference'] = {'sourceTime': time, 'opacity': opacity}
            if time < times[index]:
                continue
            if time != times[index]:
                break
            if time == first or time == last:
                _write_png(archive, 'start.png' if time == first else 'end.png', frame, stream, data)
            index += 1
            if index == len(times):
                if reference is not None:
                    _write_png(archive, 'reference.png', reference, stream, data)
                return
    raise ValueError('无法在原片中找到记录的全部关键帧')


def export_opacity_package(record: dict, source: Path, directory: Path) -> Path:
    data, times = _plan(record)
    name = hashlib.sha256(record['id'].encode()).hexdigest()[:20]
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f'MRA-opacity-{name}.zip'
    temp = None
    try:
        with open_media(source) as file:
            key = file_key(file)
            if verified_digest(file, key) != data['hash']:
                raise PlaybackSourceChanged('源视频与叠化记录不匹配')
            with NamedTemporaryFile(dir=directory, prefix='.blend-', suffix='.tmp', delete=False) as output:
                temp = Path(output.name)
                with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
                    _write_pictures(file, times, archive, data)
                    script = _SCRIPT.replace('__DATA__', json.dumps(data, ensure_ascii=True, allow_nan=False))
                    archive.writestr('create-blend.jsx', script)
                    compare = ''
                    if 'reference' in data:
                        ref = data['reference']
                        compare = (f"\n在「MRA - compare source frame」查看原片 {ref['sourceTime']:.6f} 秒，"
                                   f"与导出曲线在此帧的 {ref['opacity']:.2f}% 顶层不透明度比较。"
                                   '顶层为差值模式，较暗处表示像素更接近。独奏顶层可看原片，关闭顶层可看重建。'
                                   '此合成保留导出时的数值。')
                    archive.writestr('使用说明.txt', '完整解压到同一目录。在 AE 的「文件 → 脚本 → 运行脚本文件」中选择 create-blend.jsx。'
                                     '合成零秒对应原片选区入点。合成使用选区首尾实测静帧和顶层不透明度曲线。'
                                     '可以替换两层素材后继续编辑。\n' + color_advice(record['result']['opacity_blend']) + compare)
            check_key(file, key)
            with open_media(source) as current:
                check_key(current, key)
                # Concurrent Windows renames can briefly leave the previous name
                # delete-pending. Retry the atomic switch while holding the source lease.
                for attempt in range(5):
                    try:
                        os.replace(temp, final)
                        break
                    except PermissionError as exc:
                        if getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 4:
                            raise
                        sleep(.015 * 2**attempt)
        return final
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
