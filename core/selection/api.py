from math import isfinite
from threading import RLock
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from app import api
from app.config import get_config
from app.runtime_paths import get_runtime_paths
from db.connection import get_db_path
from db.paths import resolve_path, video_hash
from recipe.ae_recipe import shot_for_display
from selection.frames import locate_frame
from selection.jobs import SelectionJobs
from selection.models import JobSnapshot, SelectionRequest, validate_range
from selection.source import source_digest
from selection.store import SelectionStore
from video.metadata import read_video_metadata

router = APIRouter()
_previews = {}
_preview_lock = RLock()


def _store():
    api._get_library()
    return SelectionStore(get_db_path())


def _project(pid):
    try:
        return api._get_library().get_project(pid)
    except ValueError as exc:
        raise HTTPException(404, '项目不存在') from exc


def _source(pid, *, fresh=True):
    project = _project(pid)
    path = resolve_path(project.video_path)
    if path is None or not path.is_file():
        raise HTTPException(404, '源视频缺失，请在项目页重新关联同一视频')
    digest = source_digest(path, fresh=fresh, hasher=video_hash)
    if project.video_hash and not project.video_hash.startswith('legacy:') and project.video_hash != digest:
        raise HTTPException(409, '源视频内容已改变，请重新导入为新项目')
    return path, digest


def startup_recover():
    _store().recover_interrupted()
    root = get_runtime_paths().data_root / 'selection_previews'
    with _preview_lock:
        _previews.clear()
        if root.is_dir():
            for path in root.glob('*.png'):
                if path.resolve().is_relative_to(root.resolve()):
                    path.unlink(missing_ok=True)


@router.get('/projects/{pid}/frame-position')
def frame_position(pid: int, time: float = Query(ge=0, allow_inf_nan=False), pts: int | None = None,
                   direction: Literal['current', 'previous', 'next', 'presented'] = 'current'):
    path, digest = _source(pid, fresh=False)
    try:
        resolved = locate_frame(path, time, pts=pts, direction=direction)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if resolved.identity.source_hash != digest or source_digest(path, hasher=video_hash) != digest:
        raise HTTPException(409, '定位期间源视频内容改变，请重试')
    token = uuid4().hex
    directory = get_runtime_paths().data_root / 'selection_previews'
    directory.mkdir(parents=True, exist_ok=True)
    image = directory / (token + '.png')
    Image.fromarray(resolved.image[:, :, ::-1]).save(image)
    with _preview_lock:
        _previews[token] = (pid, resolved.identity, image)
        while len(_previews) > 128:
            oldest = next(iter(_previews))
            _previews.pop(oldest)[2].unlink(missing_ok=True)
    return {'frame': resolved.identity.model_dump(), 'preview_token': token,
            'preview_url': f'/api/v1/projects/{pid}/frame-preview/{token}'}


@router.get('/projects/{pid}/frame-preview/{token}')
def frame_preview(pid: int, token: str):
    with _preview_lock:
        preview = _previews.get(token)
    if preview is None or preview[0] != pid or not preview[2].is_file():
        raise HTTPException(404, '帧预览已失效，请重新定位')
    return FileResponse(preview[2], media_type='image/png')


def _preflight(config):
    if config.ocr_provider == 'paddleocr':
        from models.ocr_paths import validate_ocr_models

        validation = validate_ocr_models(config.ocr_models)
        if not validation.available:
            raise HTTPException(409, '；'.join(validation.errors))
    identity = ''
    if config.vision_provider != 'mock':
        import httpx

        from models.ollama import OllamaInspector

        inspection = OllamaInspector(config.qwen_api_base).inspect()
        if not any(m['id'] == config.qwen_model_id and m['vision'] for m in inspection['models']):
            raise HTTPException(409, '视觉模型未就绪，请在模型页配置并重新检测')
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.get(config.qwen_api_base.rstrip('/').removesuffix('/v1') + '/api/tags')
            response.raise_for_status()
            identity = next((m.get('digest', '') for m in response.json()['models']
                             if (m.get('name') or m.get('model')) == config.qwen_model_id), '')
    return identity


@router.post('/projects/{pid}/selection-analyses', status_code=202)
def submit(pid: int, request: SelectionRequest):
    store = _store()

    def snapshot_factory():
        path, digest = _source(pid)
        config = get_config().model_copy(deep=True)
        geometry = None
        if request.kind == 'frame':
            with _preview_lock:
                preview = _previews.get(request.preview_token)
            if preview is None or preview[0] != pid or preview[1] != request.frame or request.frame.source_hash != digest:
                raise HTTPException(409, '帧身份或预览失效，请重新定位当前帧')
            if not isfinite(request.frame.actual_time):
                raise HTTPException(400, '帧时间无效')
        else:
            try:
                meta = read_video_metadata(path)
                validate_range(request.start, request.end, meta['duration'])
                geometry = (meta['width'], meta['height'], meta['fps'])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        identity = '' if request.measurement else _preflight(config)
        rid = str(uuid4())
        assets = get_runtime_paths().data_root / 'selections' / str(pid) / rid
        store.create(pid, request.kind, digest, request.model_dump(mode='json'), str(assets), record_id=rid)
        return JobSnapshot(pid, path, digest, request, config, rid, assets, identity, geometry)

    return {'record_id': SelectionJobs(store, api._project_operation_lock).submit(snapshot_factory)}


@router.get('/projects/{pid}/selection-analyses')
def records(pid: int, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    _project(pid)
    return _store().list(pid, limit, offset)


def _get_record(rid: str):
    try:
        value = _store().get(rid)
    except KeyError as exc:
        raise HTTPException(404, '分析记录不存在') from exc
    return value


def _record_geometry(result, project):
    geometry = result.get('display_geometry')
    if geometry is None:
        return project.video_width, project.video_height, project.video_fps
    if not isinstance(geometry, dict):
        raise HTTPException(409, '记录的视频尺寸无效')
    return geometry.get('width'), geometry.get('height'), geometry.get('fps')


def _derive_clip_plan(value, project):
    if value['kind'] == 'clip' and value['status'] in ('done', 'completed_with_warnings'):
        result = value['result']
        width, height, _ = _record_geometry(result, project)
        result['shots'] = [shot_for_display(shot, width, height)
                           for shot in result.get('shots', [])]


@router.get('/selection-analyses/{rid}')
def record(rid: str):
    value = _get_record(rid)
    project = _project(value['project_id'])
    _derive_clip_plan(value, project)
    source = resolve_path(project.video_path)
    try:
        value['source_available'] = bool(source and source.is_file() and source_digest(source, hasher=video_hash) == value['source_hash'])
    except OSError:
        value['source_available'] = False
    return value


@router.get('/selection-analyses/{rid}/source-check')
def source_check(rid: str):
    value = _get_record(rid)
    _, digest = _source(value['project_id'])
    if digest != value['source_hash']:
        raise HTTPException(409, '源视频与分析记录不匹配，请重新关联同一视频')
    return {'source_available': True}


@router.get('/selection-analyses/{rid}/assets/{name:path}')
def asset(rid: str, name: str):
    value = _get_record(rid)
    root = resolve_path(value['assets_dir'])
    if root is None:
        raise HTTPException(404, '资产目录缺失')
    root = root.resolve()
    candidate = (root / name).resolve()
    # Only images created by our pipelines, never arbitrary files or symlinks escaping a record.
    allowed = {'frame.png'} if value['kind'] == 'frame' else {
        f"shots/{shot['shot_id']}/{frame}" for shot in value['result'].get('shots', []) for frame in shot['frames']}
    if not root.is_relative_to(get_runtime_paths().data_root.resolve()) or name not in allowed:
        raise HTTPException(404, '资产不存在')
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise HTTPException(404, '资产不存在')
    return FileResponse(candidate)


class ExportRequest(BaseModel):
    format: Literal['json', 'markdown', 'ae_blend']


@router.post('/selection-analyses/{rid}/export')
def export(rid: str, request: ExportRequest):
    from selection.export import export_selection

    try:
        value = _get_record(rid)
        directory = get_runtime_paths().exports / 'selections'
        if request.format == 'ae_blend':
            from selection.opacity_package import export_opacity_package

            project = _project(value['project_id'])
            source = resolve_path(project.video_path)
            if source is None:
                raise HTTPException(404, '源视频缺失，请先重新关联原片')
            path = export_opacity_package(value, source, directory)
            return {'path': str(path)}
        if request.format == 'markdown':
            _derive_clip_plan(value, _project(value['project_id']))
        path = export_selection(value, request.format, directory)
        return {'path': str(path)}
    except FileNotFoundError as exc:
        raise HTTPException(404, '文件已移除，请检查源视频和导出目录') from exc
    except OSError as exc:
        raise HTTPException(409, f'无法读取素材或写入导出目录：{exc}') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/selection-analyses/{rid}/shots/{shot_id}/export/ae')
def export_motion_script(rid: str, shot_id: str, padded: bool = False):
    value = _get_record(rid)
    if value['status'] not in ('done', 'completed_with_warnings') or value['kind'] != 'clip':
        raise HTTPException(409, '仅已完成的片段分析支持动画脚本')
    shot = next((s for s in value['result'].get('shots', []) if s.get('shot_id') == shot_id), None)
    if shot is None:
        raise HTTPException(404, '片段镜头不存在')
    project = _project(value['project_id'])
    return api._export_motion_script(shot, *_record_geometry(value['result'], project), padded=padded)
