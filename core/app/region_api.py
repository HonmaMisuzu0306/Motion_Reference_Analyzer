"""User-selected image region operations on the current, verified working shot."""
import base64
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Annotated
from uuid import uuid4
from weakref import ref

import av
import cv2
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app import api
from cv.frame_sampler import _check_stream_pixels, _resize_for_analysis
from cv.region_track import (
    MAX_DECODED_FRAMES,
    MAX_DURATION,
    MAX_SOURCE_PIXELS,
    NormalizedBox,
    RegionTrack,
    track_region,
)
from cv.two_pin import TwoPinTrack, derive_two_pin
from db.paths import resolve_path
from recipe.region_ae import export_region_ae_script
from recipe.two_pin_ae import export_two_pin_ae_script
from video.orientation import display_bgr
from video.playback_file import (
    PlaybackSourceChanged,
    check_key,
    file_key,
    open_media,
    verified_digest,
)
from video.timing import relative_frame_time, video_origin

router = APIRouter(prefix='/shots')
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class IdentityRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    identity: Digest
    library_id: int | None = Field(default=None, gt=0)


class RegionRequest(IdentityRequest):
    anchor_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    box: NormalizedBox


class TwoPinRequest(IdentityRequest):
    track_a_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    track_b_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    same_layer_confirmed: bool


@dataclass
class StoredTrack:
    identity: str
    shot_id: str
    library_id: int | None
    shot_range: tuple[float, float]
    anchor_time: float
    end_time: float
    track: RegionTrack | TwoPinTrack
    box: NormalizedBox | None
    expires: float


# Every caller holds the working project's operation lock (including source swaps).
_owner = None
_tracks: OrderedDict[str, StoredTrack] = OrderedDict()
MAX_TRACKS = 32
TRACK_TTL_SECONDS = 30 * 60


def _current_shot(shot_id, identity, library_id):
    global _owner
    project = api._project_state
    if _owner is None or _owner() is not project:
        _tracks.clear()
        _owner = ref(project)
    now = monotonic()
    while _tracks and next(iter(_tracks.values())).expires <= now:
        _tracks.popitem(last=False)
    if project.video is None or project.analysis_status not in {'done', 'completed_with_warnings'}:
        raise HTTPException(409, '请先完成当前视频的镜头分析')
    if not project.source_hash or project.source_hash != identity:
        raise HTTPException(409, '工作区素材已改变，请重新打开当前镜头')
    matches = (shot for shot in project.shots
               if shot.shot_id == shot_id and (library_id is None or library_id == shot.library_id))
    shot = next(matches, None)
    if shot is None:
        raise HTTPException(404, '当前项目中没有这个镜头')
    if next(matches, None) is not None:
        raise HTTPException(409, '多个镜头使用相同编号，请从当前资料库记录重新打开镜头')
    return project, shot


@contextmanager
def _verified_source(project, identity):
    path = resolve_path(project.video_path)
    if path is None:
        raise HTTPException(404, '未保存当前素材路径，请重新导入')
    try:
        with open_media(path) as file:
            key = file_key(file)
            if verified_digest(file, key) != identity:
                raise HTTPException(409, '源文件与已分析的素材不符，请重新导入')
            file.seek(0)
            yield file
            check_key(file, key)
            # Path replacement on platforms without Windows read sharing must
            # also invalidate the result; decoding always used the original handle.
            with open_media(path) as current:
                if file_key(current) != key:
                    raise HTTPException(409, '计算期间素材文件改变，请重新导入')
    except PlaybackSourceChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, '当前素材已移除') from exc
    except (OSError, av.FFmpegError, cv2.error, ValueError) as exc:
        raise HTTPException(422, f'无法处理当前素材：{exc}') from exc


def _region_picture(file, shot, target):
    """Nearest display frame inside this shot, with bounded keyframe pre-roll."""
    with av.open(file) as container:
        stream = container.streams.video[0]
        _check_stream_pixels(stream, MAX_SOURCE_PIXELS)
        container.seek(int((target + video_origin(stream)) / stream.time_base),
                       stream=stream, backward=True)
        best = None
        best_time = None
        for index, frame in enumerate(container.decode(stream)):
            if index >= MAX_DECODED_FRAMES:
                raise ValueError('定位首帧超出解码预算，请选择附近的其他画面')
            if frame.width * frame.height > MAX_SOURCE_PIXELS:
                raise ValueError('源视频编码画幅超出像素预算')
            time = relative_frame_time(stream, frame.pts, frame.time_base)
            if time >= shot.time.end:
                break
            if time < shot.time.start:
                continue
            if best_time is None or abs(time-target) < abs(best_time-target):
                best, best_time = frame, time
            if time >= target:
                break
        if best is None:
            raise ValueError('镜头范围内没有可用图像')
        image = display_bgr(best, stream)
        h, w = image.shape[:2]
        ok, jpeg = cv2.imencode('.jpg', _resize_for_analysis(image, 960),
                                [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError('无法编码取景图')
        return best_time, w, h, 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')


@router.get('/{shot_id}/region-frame')
@api._exclusive_project_operation
def region_frame(shot_id: str, identity: Digest, time: Annotated[float, Query(ge=0, allow_inf_nan=False)],
                 library_id: Annotated[int | None, Query(gt=0)] = None):
    project, shot = _current_shot(shot_id, identity, library_id)
    if not shot.time.start <= time < shot.time.end:
        raise HTTPException(422, '取帧时间须位于当前镜头内')
    with _verified_source(project, identity) as file:
        time, width, height, data_url = _region_picture(file, shot, time)
    if (width, height) != (project.video.width, project.video.height):
        raise HTTPException(409, '显示画幅与原分析不一致，请重新分析视频')
    return {'source_id': identity, 'source_time': time, 'frame_width': width,
            'frame_height': height, 'image_data_url': data_url}


@router.post('/{shot_id}/region-track')
@api._exclusive_project_operation
def region_track(shot_id: str, body: RegionRequest):
    project, shot = _current_shot(shot_id, body.identity, body.library_id)
    if not (shot.time.start <= body.anchor_time < body.end_time <= shot.time.end
            and body.end_time - body.anchor_time <= MAX_DURATION):
        raise HTTPException(422, '跟踪范围须位于当前镜头内，最长 30 秒')
    with _verified_source(project, body.identity) as file:
        track = track_region(file, body.anchor_time, body.end_time, body.anchor_time, body.box)
    if track.status == 'anchor_mismatch':
        raise HTTPException(409, '所选时间与实际首帧不符，请重新取帧')
    if track.status != 'no_frames' and (track.frame_width, track.frame_height) != (project.video.width, project.video.height):
        raise HTTPException(409, '显示画幅与原分析不一致，请重新分析视频')
    return _store_track(shot, body.identity, body.anchor_time, body.end_time, track, body.box)


def _store_track(shot, identity, anchor_time, end_time, track, box=None):
    track_id = uuid4().hex
    _tracks[track_id] = StoredTrack(identity, shot.shot_id, shot.library_id, (shot.time.start, shot.time.end),
                                    anchor_time, end_time, track, box, monotonic() + TRACK_TTL_SECONDS)
    while len(_tracks) > MAX_TRACKS:
        _tracks.popitem(last=False)
    return {'track_id': track_id, 'track': track}


def _saved_track(track_id, shot, identity, kind):
    record = _tracks.get(track_id)
    if (record is None or not isinstance(record.track, kind) or record.shot_id != shot.shot_id
            or record.library_id != shot.library_id or record.identity != identity
            or record.shot_range != (shot.time.start, shot.time.end)):
        raise HTTPException(404, '跟踪结果已过期或属于其他镜头，请重新跟踪')
    return record


@router.post('/{shot_id}/two-pin-track')
@api._exclusive_project_operation
def two_pin_track(shot_id: str, body: TwoPinRequest):
    project, shot = _current_shot(shot_id, body.identity, body.library_id)
    if not body.same_layer_confirmed:
        raise HTTPException(422, '请先确认两个标记属于同一个刚性平面图案')
    if body.track_a_id == body.track_b_id:
        raise HTTPException(422, '请分别选择并跟踪两个不同的标记')
    a = _saved_track(body.track_a_id, shot, body.identity, RegionTrack)
    b = _saved_track(body.track_b_id, shot, body.identity, RegionTrack)
    if a.anchor_time != b.anchor_time or a.end_time != b.end_time:
        raise HTTPException(409, '两个标记必须使用相同的定帧和结束时间，请重新跟踪')
    with _verified_source(project, body.identity):
        track = derive_two_pin(a.track, b.track, a.box, b.box)
    return _store_track(shot, body.identity, a.anchor_time, a.end_time, track)


@router.post('/{shot_id}/region-tracks/{track_id}/export/ae')
@api._exclusive_project_operation
def region_export(shot_id: str, track_id: str, body: IdentityRequest):
    project, shot = _current_shot(shot_id, body.identity, body.library_id)
    record = _saved_track(track_id, shot, body.identity, RegionTrack)
    return _export_verified(project, record, 'region', export_region_ae_script)


@router.post('/{shot_id}/two-pin-tracks/{track_id}/export/ae')
@api._exclusive_project_operation
def two_pin_export(shot_id: str, track_id: str, body: IdentityRequest):
    project, shot = _current_shot(shot_id, body.identity, body.library_id)
    record = _saved_track(track_id, shot, body.identity, TwoPinTrack)
    return _export_verified(project, record, 'two_pin', export_two_pin_ae_script)


def _export_verified(project, record, prefix, exporter):
    path = api.OUTPUT_DIR / 'ae_exports' / f'{prefix}_{uuid4().hex}.jsx'
    pending = path.with_suffix('.tmp')
    try:
        with _verified_source(project, record.identity):
            try:
                exporter(record.track, source_start=record.anchor_time, source_end=record.end_time,
                         fps=project.video.fps, path=pending)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            except OSError as exc:
                raise HTTPException(503, '无法写入区域跟踪脚本，请检查输出目录') from exc
        pending.replace(path)
    except OSError as exc:
        raise HTTPException(503, '无法写入区域跟踪脚本，请检查输出目录') from exc
    finally:
        pending.unlink(missing_ok=True)
    return {'path': str(path.resolve())}
