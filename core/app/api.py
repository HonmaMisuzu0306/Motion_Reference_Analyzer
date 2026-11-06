import json
import logging
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from threading import Lock, RLock
from typing import Literal
from uuid import uuid4

import av
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from app.config import get_config
from app.playback_response import PlaybackResponse
from app.progress import AnalysisProgressTracker
from app.runtime_paths import get_runtime_paths
from audio.analyzer import analyze_audio
from audio.cache import AudioCache
from audio.rhythm import VIDEO_CLOCK_VERSION, apply_rhythm
from cv import MotionCache, analyze_shot_motion, fuse_motion
from cv.cache import CV_ALGORITHM_VERSION
from db import ReferenceLibrary
from db.library import SourceIdentityMismatch
from db.models import FilterSet
from db.paths import resolve_path, video_hash
from ocr import ShotOCRAnalyzer, create_ocr_provider
from ocr.pending_cache import PendingOCRCache
from ocr.semantic import TypographyCache, TypographySemanticAnalyzer
from recipe.ae_recipe import generate_ae_recipe, has_global_totals, shot_for_display
from recipe.ae_script import export_ae_script
from recipe.difficulty import estimate_difficulty
from recipe.keyframes import RECIPE_VERSION
from recipe.report import animation_plan_markdown
from schemas import (
    FilterRequest,
    LibraryProjectSummary,
    LibrarySearchResponse,
    LibraryShotSummary,
    Project,
    Shot,
    ShotTagsUpdate,
    TagCreate,
    TagResponse,
    TimeRange,
    VideoInfo,
)
from schemas.audio import AudioAnalysis
from selection.static import STATIC_PROMPT_VERSION, StaticVisionAnalysis, static_recipe
from video.frame_sampler import create_contact_sheet, sample_frames
from video.metadata import read_video_metadata
from video.playback import PlaybackSourceChanged, open_playback
from video.scene_detect import detect_scenes
from video.scene_features import SCENE_DETECT_VERSION
from vision.analyzer import ShotAnalyzer, update_shot_with_analysis
from vision.cache import VisionCache
from vision.factory import create_vision_provider

router = APIRouter()

# MVP 阶段使用内存存储项目状态
_project_state: Project = Project()
_project_operation_lock = Lock()


def _exclusive_project_operation(operation):
    """Reject overlapping mutations of the single working project."""
    @wraps(operation)
    def guarded(*args, **kwargs):
        if not _project_operation_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="当前项目正在处理其他操作，请完成后重试")
        try:
            return operation(*args, **kwargs)
        finally:
            _project_operation_lock.release()
    return guarded

# SQLite Reference Library
_library: ReferenceLibrary | None = None
_library_lock = RLock()


def _get_library() -> ReferenceLibrary:
    """Lazy initialize the Reference Library."""
    global _library
    with _library_lock:
        if _library is None:
            _library = ReferenceLibrary()
        return _library


def reset_library() -> None:
    """Reset the library singleton. Useful for tests."""
    global _library
    from db.connection import close_connection

    with _library_lock:
        _library = None
        close_connection()


# 输出目录
OUTPUT_DIR = get_runtime_paths().projects


def _ensure_project_dirs(project_name: str, *, project: Project | None = None) -> Path:
    project = project if project is not None else _project_state
    project_dir = (resolve_path(project.assets_dir)
                   if project.project_name == project_name and project.assets_dir
                   else OUTPUT_DIR / project_name)
    (project_dir / "shots").mkdir(parents=True, exist_ok=True)
    (project_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (project_dir / "thumbnails").mkdir(parents=True, exist_ok=True)
    return project_dir


class VideoImportRequest(BaseModel):
    path: str


@router.post("/video/import")
@_exclusive_project_operation
def import_video(req: VideoImportRequest):
    global _project_state

    video_path = Path(req.path)
    try:
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if not video_path.is_file():
            raise ValueError("请选择视频文件，不能导入文件夹")
        digest = video_hash(video_path)
        video = VideoInfo(**read_video_metadata(video_path))
        if video_hash(video_path) != digest:
            raise HTTPException(409, '导入期间视频内容改变，原项目保持不变，请重新导入')
        project_name = f"{video_path.stem}_{digest[:8]}"
        project = Project(
            video=video,
            video_path=str(video_path.resolve()),
            source_hash=digest,
            project_name=project_name,
            assets_dir=str((OUTPUT_DIR / project_name).resolve()),
            analysis_status="imported",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"视频文件不存在或已被移除: {video_path}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"无法读取视频，请检查文件权限: {video_path}") from exc
    except (OSError, ValueError, av.FFmpegError) as exc:
        raise HTTPException(status_code=400, detail=f"无法导入视频，请检查文件是否完整且包含视频画面: {exc}") from exc

    # Publish only a complete candidate; polling and failed imports keep the old project intact.
    _project_state = project

    return {
        "status": "ok",
        "video": _project_state.video.model_dump(),
        "video_source_id": _video_source_id(project),
    }


def _persist_project_state() -> Path:
    """将当前项目状态写入 output/<project>/project.json。"""
    project_dir = _ensure_project_dirs(_project_state.project_name)
    output_path = project_dir / "project.json"
    output_path.write_text(
        json.dumps(_project_state.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def _persist_to_library(*, raise_identity_conflict: bool = False) -> bool:
    """将当前项目状态和 Shots 持久化到 SQLite Reference Library。"""
    try:
        lib = _get_library()
        _project_state.library_project_id = lib.save_analysis(_project_state)
        _project_state.library_warning = ""
        from projects.session import SessionState, write_session
        write_session(SessionState(project_id=_project_state.library_project_id))
        return True
    except Exception as exc:
        if raise_identity_conflict and isinstance(exc, SourceIdentityMismatch):
            raise HTTPException(409, str(exc)) from exc
        logging.getLogger(__name__).warning("保存到 Reference Library 失败: %s", exc)
        _project_state.library_warning = f"Reference Library 保存失败，可重试: {exc}"
        return False


def _analyze_project_audio(video_path: Path, force: bool = False, *, project: Project | None = None) -> AudioAnalysis:
    project = project if project is not None else _project_state
    config = get_config()
    try:
        result = analyze_audio(video_path, sample_rate=config.audio_sample_rate,
                               hop_length=config.audio_hop_length, max_duration=config.audio_max_duration,
                               cache=AudioCache(config.audio_cache_dir), force=force)
    except Exception as exc:
        result = AudioAnalysis(status='error', message=f'音频分析失败: {exc}')
    project.audio = result
    project.rhythm_summary = apply_rhythm(project.shots, result, config.beat_sync_tolerance_ms)
    for shot in project.shots:
        shot.provider_versions['audio'] = {'method': result.method, 'librosa': result.library_version}
    return result


class AudioAnalyzeRequest(BaseModel):
    force: bool = False


@router.post('/video/analyze-audio')
@_exclusive_project_operation
def analyze_project_audio(req: AudioAnalyzeRequest | None = None):
    """Retry only audio, reusing the current cuts and preserving all other analyses."""
    global _project_state
    source = _resolve_video_path()
    digest = video_hash(source)
    if _project_state.source_hash and digest != _project_state.source_hash:
        raise HTTPException(409, '源视频内容已改变，不能将新音频与旧镜头匹配，请重新导入')
    candidate = _project_state.model_copy(deep=True)
    result = _analyze_project_audio(source, force=bool(req and req.force), project=candidate)
    if video_hash(source) != digest:
        raise HTTPException(409, '音频分析期间源视频内容改变，保留原分析结果，请重新导入')
    candidate.source_hash = digest
    _project_state = candidate
    for shot in _project_state.shots:
        if shot.ae_recipe:
            shot.ae_recipe['timing'] = {**shot.rhythm.model_dump(), 'notes': 'Measured cut alignment against estimated beats; not a claim about author intent.'}
    if _project_state.analysis_status in {'done', 'completed_with_warnings'}:
        _project_state.analysis_status = ('completed_with_warnings' if result.status == 'error' or
                                         _project_state.rhythm_summary.excluded_shot_count or
                                         any(s.analysis_error for s in _project_state.shots) else 'done')
        _project_state.analysis_message = '音频分析完成' if result.status != 'error' else result.message
        _project_state.progress.status = _project_state.analysis_status
        _project_state.progress.message = _project_state.analysis_message
        tracker = AnalysisProgressTracker(_project_state)
        tracker.complete_optional_stage('audio_analysis', result.status, result.message)
    if get_config().auto_save_to_library and _project_state.shots:
        if not _persist_to_library() and _project_state.analysis_status == 'done':
            _project_state.analysis_status = _project_state.progress.status = 'completed_with_warnings'
    _persist_project_state()
    return {'status': 'ok', 'audio': result.model_dump(),
            'rhythm_summary': _project_state.rhythm_summary.model_dump(),
            'library_warning': _project_state.library_warning}


class AnalyzeRequest(BaseModel):
    mode: Literal['full','basic'] = 'full'

@router.post("/video/analyze")
@_exclusive_project_operation
def analyze_video(req: AnalyzeRequest | None = None):
    global _project_state
    tracker = AnalysisProgressTracker(_project_state)

    if _project_state.video is None or _project_state.video_path is None:
        tracker.set_error("preparing", "未导入视频")
        raise HTTPException(status_code=400, detail=_project_state.analysis_message)

    tracker.start_analysis()
    # Polling sees live progress on the old, verified result. New evidence remains
    # private until its source identity has been checked again after analysis.
    candidate = _project_state.model_copy(deep=True)

    has_warnings = False
    ocr_cache = None

    try:
        config = get_config()
        basic=bool(req and req.mode=='basic')
        if not basic and config.ocr_provider=='paddleocr':
            from models.ocr_paths import validate_ocr_models
            validation=validate_ocr_models(config.ocr_models)
            if not validation.available:
                raise HTTPException(409,'；'.join(validation.errors))
        video_path = _resolve_video_path()
        source_hash = video_hash(video_path)
        if candidate.source_hash and source_hash != candidate.source_hash:
            raise HTTPException(409, '源视频内容已改变，请重新导入为新项目')
        if candidate.library_project_id:
            known=_get_library().get_project(candidate.library_project_id)
            if known.video_hash and not known.video_hash.startswith('legacy:') and source_hash != known.video_hash:
                raise HTTPException(409,'源视频内容已改变，请重新导入为新项目')
        # An archived import may have stored coded dimensions before display
        # orientation support. Refresh the private candidate after source verification.
        if candidate.library_project_id:
            candidate.video = VideoInfo(**read_video_metadata(video_path))
        if not basic and config.vision_provider != 'mock':
            from models.ollama import OllamaInspector
            models=OllamaInspector(config.qwen_api_base).inspect()
            if not any(m['id']==config.qwen_model_id and m['vision'] for m in models['models']):
                raise HTTPException(409,'视觉模型未就绪，请在模型页配置，或选择基础分析')
        # Each run owns its assets; archived ranges/versions must keep their frames.
        candidate.assets_dir = str((OUTPUT_DIR / candidate.project_name /
                                         'runs' / uuid4().hex).resolve())
        project_dir = _ensure_project_dirs(candidate.project_name, project=candidate)

        # 1. 分镜
        tracker.start_stage("scene_detect", "正在检测镜头切换")
        shots_meta = detect_scenes(video_path)
        tracker.complete_stage("scene_detect")

        # 2. 代表帧提取与 Contact Sheet
        tracker.start_stage("extract_frames", "正在提取代表帧")
        shots = []
        static_analyses = {}

        for meta in shots_meta:
            shot_id = meta["shot_id"]
            shot_dir = project_dir / "shots" / shot_id
            shot_dir.mkdir(parents=True, exist_ok=True)

            duration = meta["duration"]
            frame_count = 5 if duration > 5.0 else 3

            sampled = sample_frames(video_path, meta["start"], meta["end"], count=frame_count)

            frame_files = []
            frames = []
            for fidx, frame_info in enumerate(sampled, start=1):
                frame_path = shot_dir / f"frame_{fidx:02d}.jpg"
                Image.fromarray(frame_info["image"][:, :, ::-1]).save(frame_path, quality=90)
                frame_files.append(frame_path.name)
                frames.append(frame_info["image"])

            contact_path = shot_dir / "contact.jpg"
            create_contact_sheet(frames, contact_path)

            shot = Shot(
                shot_id=shot_id,
                time=TimeRange(**meta),
                frames=frame_files,
                frame_timestamps=[frame['timestamp'] for frame in sampled],
                pipeline_version='mra-pipeline-v6-spatial-evidence',
                provider_versions={'video_clock': {'version': VIDEO_CLOCK_VERSION},
                                   'representative_frames': {'strategy': 'nearest-actual-pts-half-open-unique-v1',
                                                             'requested_count': frame_count},
                                   'scene_detection': {'version': SCENE_DETECT_VERSION},
                                   'cv': {'version': CV_ALGORITHM_VERSION, 'target_fps': config.cv_target_fps,
                                          'max_long_edge': config.cv_max_long_edge},
                                   'recipe': {'version': RECIPE_VERSION}},
            )
            shots.append(shot)

        candidate.shots = shots
        tracker.complete_stage("extract_frames")

        total_shots = len(candidate.shots)

        tracker.start_stage('audio_analysis', '正在检测音频节拍与瞬态')
        audio_result = _analyze_project_audio(video_path, project=candidate)
        has_warnings = audio_result.status == 'error'
        tracker.complete_optional_stage('audio_analysis', audio_result.status, audio_result.message)

        model_info={'provider':'disabled'}
        provider=None
        if not basic:
            # 3. VLM 分析
            tracker.start_stage("vision_analysis", "正在运行 AI 视觉分析")
            provider = create_vision_provider(config)
            model_info = provider.get_model_info()
            model_label = model_info.get("model_id", "AI 模型")
            cache = VisionCache(config.vision_cache_dir)
            analyzer = ShotAnalyzer(
                provider=provider,
                cache=cache,
                max_retries=config.vision_max_retries,
            )

            for idx, shot in enumerate(candidate.shots, start=1):
                try:
                    if len(shot.frames) == 1:
                        shot.provider_versions['vision'] = {**model_info, 'analysis_mode': 'static_frame',
                                                            'prompt_version': STATIC_PROMPT_VERSION}
                        analysis = provider.analyze_static_frame(project_dir / 'shots' / shot.shot_id / shot.frames[0],
                            {'source_hash': source_hash, 'actual_time': shot.frame_timestamps[0],
                             'time_origin': 'source_video_seconds', 'shot_id': shot.shot_id})
                        analysis = StaticVisionAnalysis.model_validate(analysis)
                    else:
                        analysis = analyzer.analyze(
                            shot, project_dir, video_filename=candidate.video.filename)
                    if analysis.analysis_error:
                        raise RuntimeError(analysis.analysis_error)
                    if len(shot.frames) == 1:
                        static_analyses[shot.shot_id] = analysis
                        shot.observations = analysis.observations.model_dump()
                        shot.typography = analysis.typography.model_dump()
                        shot.visual_effects = [effect.model_dump() for effect in analysis.visual_effects]
                        shot.ae_hypothesis = analysis.ae_hypothesis.model_dump()
                        shot.motion = {}
                    else:
                        update_shot_with_analysis(shot, analysis)
                    tracker.shot_complete(
                        "vision_analysis",
                        idx,
                        total_shots,
                        f"{model_label} 正在分析 {shot.shot_id} ({idx}/{total_shots})",
                    )
                except Exception as exc:
                    shot.analysis_error = f"Vision 失败: {exc}"
                    tracker.shot_failed("vision_analysis", idx, total_shots, str(exc))
                    has_warnings = True

            tracker.complete_stage("vision_analysis")

        else:
            tracker.complete_optional_stage('vision_analysis','skipped','基础分析：省略视觉模型')
            for shot in candidate.shots:
                shot.provider_versions['vision']=model_info

        # 4. CV 运动测量
        tracker.start_stage("cv_analysis", "正在测量全局运动")
        cv_cache = MotionCache(config.cv_cache_dir)
        pending_cv_cache = []
        for idx, shot in enumerate(candidate.shots, start=1):
            try:
                cached = cv_cache.get(
                    video_path,
                    shot.time.start,
                    shot.time.end,
                    config.cv_target_fps,
                    config.cv_max_long_edge,
                    source_hash=source_hash,
                )
                if cached is not None:
                    shot.measured_motion = cached
                else:
                    measured = analyze_shot_motion(
                        video_path,
                        shot.time.start,
                        shot.time.end,
                        original_width=candidate.video.width,
                        original_height=candidate.video.height,
                        target_fps=config.cv_target_fps,
                        max_long_edge=config.cv_max_long_edge,
                    )
                    shot.measured_motion = measured
                    pending_cv_cache.append((shot, measured))

                shot.motion_summary = fuse_motion(shot.motion, shot.measured_motion)
                tracker.shot_complete(
                    "cv_analysis",
                    idx,
                    total_shots,
                    f"正在测量 {shot.shot_id} 的全局运动 ({idx}/{total_shots})",
                )
            except Exception as exc:
                shot.analysis_error = f"CV 失败: {exc}"
                tracker.shot_failed("cv_analysis", idx, total_shots, str(exc))
                has_warnings = True

        tracker.complete_stage("cv_analysis")

        if not basic:
            # 5. OCR 分析
            tracker.start_stage("ocr_analysis", "正在识别文字")
            ocr_provider = create_ocr_provider(config)
            for shot in candidate.shots:
                shot.provider_versions.setdefault('vision', model_info)
                shot.provider_versions['ocr'] = ocr_provider.get_model_info()
            ocr_cache = PendingOCRCache(config.ocr_cache_dir, video_path, source_hash)
            ocr_analyzer = ShotOCRAnalyzer(
                provider=ocr_provider,
                cache=ocr_cache,
                target_fps=config.ocr_target_fps,
                min_frames=config.ocr_min_frames,
                max_frames=config.ocr_max_frames,
                max_long_edge=config.ocr_max_long_edge,
                strict_range=True,
            )

            for idx, shot in enumerate(candidate.shots, start=1):
                try:
                    ocr_result = ocr_analyzer.analyze(
                        video_path,
                        shot.time.start,
                        shot.time.end,
                    )
                    if ocr_result.analysis_error:
                        raise RuntimeError(ocr_result.analysis_error)
                    shot.text_regions = ocr_result.text_regions
                    shot.typography_tracks = ocr_result.typography_tracks if len(shot.frames) > 1 else []
                    if len(shot.frames) == 1:
                        shot.text_regions = [region for region in shot.text_regions
                                             if abs(region.frame_timestamp - shot.frame_timestamps[0]) <= 1e-9]
                    tracker.shot_complete(
                        "ocr_analysis",
                        idx,
                        total_shots,
                        f"正在识别 {shot.shot_id} 的文字 ({idx}/{total_shots})",
                    )
                except Exception as exc:
                    shot.analysis_error = f"OCR 失败: {exc}"
                    tracker.shot_failed("ocr_analysis", idx, total_shots, str(exc))
                    has_warnings = True

            tracker.complete_stage("ocr_analysis")

            # 6. Typography 语义分析
            tracker.start_stage("typography_analysis", "正在分析 Typography")
            typography_cache = TypographyCache(config.typography_cache_dir)
            typography_analyzer = TypographySemanticAnalyzer(
                provider=provider,
                cache=typography_cache,
                max_tracks_per_shot=config.typography_max_tracks_per_shot,
                confidence_threshold=config.typography_confidence_threshold,
                max_retries=config.vision_max_retries,
            )

            for idx, shot in enumerate(candidate.shots, start=1):
                try:
                    if not shot.typography_tracks:
                        tracker.shot_complete(
                            "typography_analysis",
                            idx,
                            total_shots,
                            f"{shot.shot_id} 无文字可分析 ({idx}/{total_shots})",
                        )
                        continue

                    shot_dir = project_dir / "shots" / shot.shot_id
                    image_path = shot_dir / shot.frames[0] if shot.frames else None
                    if image_path is None or not image_path.exists():
                        raise RuntimeError("缺少代表帧图片")

                    typography_analyzer.analyze_tracks(
                        shot.typography_tracks,
                        image_path,
                        shot.shot_id,
                        video_path=video_path,
                    )
                    errors = [t.typography_analysis.analysis_error for t in shot.typography_tracks
                              if t.typography_analysis and t.typography_analysis.analysis_error]
                    if errors:
                        raise RuntimeError("; ".join(errors))
                    tracker.shot_complete(
                        "typography_analysis",
                        idx,
                        total_shots,
                        f"正在分析 {shot.shot_id} 的 Typography ({idx}/{total_shots})",
                    )
                except Exception as exc:
                    shot.analysis_error = f"Typography 失败: {exc}"
                    tracker.shot_failed("typography_analysis", idx, total_shots, str(exc))
                    has_warnings = True

            tracker.complete_stage("typography_analysis")

        else:
            for stage in ['ocr_analysis','typography_analysis']:
                tracker.complete_optional_stage(stage,'skipped','基础分析：省略文字模型')
            for shot in candidate.shots:
                shot.provider_versions['ocr']={'provider':'disabled','reason':'basic'}
                shot.provider_versions['typography']={'provider':'disabled','reason':'basic'}

        # 7. Recipe 生成
        tracker.start_stage("recipe_generation", "正在生成 AE Recipe")
        for idx, shot in enumerate(candidate.shots, start=1):
            try:
                if len(shot.frames) == 1:
                    shot.motion = {}
                    shot.typography_tracks = []
                    recipe = static_recipe(static_analyses.get(shot.shot_id, StaticVisionAnalysis()), shot.text_regions)
                    measured_recipe = generate_ae_recipe(shot.model_dump())
                    measured_plan = measured_recipe['animation_plan']
                    if measured_plan['evidence_source'] == 'measured' and measured_plan['curves']:
                        recipe.update({key: measured_recipe[key] for key in (
                            'version', 'transform', 'animation_plan', 'measured_motion')})
                        recipe['camera'] = {'status': 'measured_only',
                                            'reason': '单张代表帧只提供静态语义；整体运动仅来自独立连续 CV 测量'}
                        recipe['animation'] = {'status': 'measured_only',
                                               'reason': '仅提供连续 CV 曲线，不推断语义动画或转场'}
                    else:
                        recipe['measured_motion'] = measured_recipe['measured_motion']
                        recipe['animation']['reason'] = '单张代表帧不支持时间推断，独立 CV 也未提供可靠连续运动曲线'
                    if basic:
                        recipe['basis'] = '基础分析已省略视觉和文字模型；静态内容未做 AI 推断，运动仅参考独立 CV 测量'
                    recipe['notes'] = ['单张代表帧无法判断缓动、转场或文字进出动画；真实采样时间保留在 frame_timestamps。']
                else:
                    recipe = generate_ae_recipe(shot.model_dump())
                recipe["difficulty"] = estimate_difficulty(recipe)
                shot.ae_recipe = recipe
                tracker.update_stage(
                    "recipe_generation",
                    completed=idx,
                    total=total_shots,
                    message=f"正在生成 {shot.shot_id} 的 AE Recipe ({idx}/{total_shots})",
                    current_shot=idx,
                )
            except Exception as exc:
                shot.analysis_error = f"Recipe 失败: {exc}"
                tracker.shot_failed("recipe_generation", idx, total_shots, str(exc))
                has_warnings = True

        tracker.complete_stage("recipe_generation")

        # 6. 保存
        tracker.start_stage("saving", "正在保存分析结果")
        if video_hash(video_path) != source_hash:
            raise HTTPException(409, '分析期间源视频内容改变，结果和运动缓存未发布，请重新导入')
        candidate.source_hash = source_hash
        candidate.progress = _project_state.progress
        _project_state = candidate
        tracker.project = candidate
        for shot, measured in pending_cv_cache:
            try:
                cv_cache.set(video_path, shot.time.start, shot.time.end, measured,
                             config.cv_target_fps, config.cv_max_long_edge, source_hash=source_hash)
            except OSError:
                logging.getLogger(__name__).warning('CV 缓存写入失败，保留本次分析结果', exc_info=True)
        if ocr_cache is not None:
            try:
                ocr_cache.publish()
            except OSError:
                logging.getLogger(__name__).warning('OCR 缓存写入失败，保留本次分析结果', exc_info=True)
        _project_state.source_hash = source_hash
        _persist_project_state()
        _project_state.analysis_status = "completed_with_warnings" if has_warnings else "done"
        _project_state.analysis_message = '分析完成（部分步骤存在警告）' if has_warnings else '分析完成'
        if config.auto_save_to_library and not _persist_to_library():
            has_warnings = True
        tracker.complete_stage("saving")

        tracker.finish_analysis(has_warnings=has_warnings)
        _persist_project_state()

        return {
            "status": "ok",
            "shots": [s.model_dump() for s in _project_state.shots],
            "library_warning": _project_state.library_warning,
        }

    except HTTPException as exc:
        tracker.set_error(_project_state.progress.stage,str(exc.detail))
        raise
    except Exception as exc:
        tracker.set_error(_project_state.progress.stage, f"分析失败: {exc}")
        raise HTTPException(status_code=500, detail=_project_state.analysis_message) from exc


def reset_project_state() -> None:
    """重置内存中的项目状态，主要用于测试。"""
    global _project_state
    _project_state = Project()


def _resolve_video_path() -> Path:
    """根据当前项目状态解析视频文件路径。"""
    if _project_state.video_path:
        path = Path(_project_state.video_path)
        if path.exists():
            return path

    if _project_state.video is None:
        raise HTTPException(status_code=400, detail="未导入视频")

    filename = _project_state.video.filename
    candidates = [
        OUTPUT_DIR.parent / "samples" / filename,
        Path(filename),
    ]
    for cand in candidates:
        if cand.exists():
            return cand

    raise HTTPException(status_code=404, detail=f"找不到视频文件: {filename}")


def _video_source_id(project: Project) -> str:
    if not project.video_path:
        return ""
    return project.source_hash or project.video_path


@router.get("/project/status")
def project_status():
    project = _project_state
    return {
        "status": project.analysis_status,
        "project_name": project.display_name or project.project_name,
        "message": project.analysis_message,
        "video": project.video.model_dump() if project.video else None,
        "video_path": project.video_path,
        "video_source_id": _video_source_id(project),
        "shot_count": len(project.shots),
        "progress": project.progress.model_dump_safe(),
        "library_warning": project.library_warning,
        "library_project_id": project.library_project_id,
        "audio": project.audio.model_dump(),
        "rhythm_summary": project.rhythm_summary.model_dump(),
    }


@router.get('/video/source')
def project_video_source(identity: str | None = None):
    project = _project_state
    if identity is not None and identity not in (_video_source_id(project), project.video_path):
        raise HTTPException(409, '播放请求属于另一份素材，请重新打开镜头')
    if not project.video_path and project.video is None:
        raise HTTPException(400, '未导入视频')
    return _verified_playback(resolve_path(project.video_path), project.source_hash)


def _verified_playback(path: Path | None, expected_hash: str | None):
    if path is None or not path.is_file():
        raise HTTPException(404, '源视频缺失，请在项目页重新关联同一视频')
    try:
        digest = expected_hash if expected_hash and not expected_hash.startswith('legacy:') else None
        playable, file, key = open_playback(path, OUTPUT_DIR / 'playback_cache', digest)
        try:
            return PlaybackResponse(playable, file, key)
        except BaseException:
            file.close()
            raise
    except PlaybackSourceChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, '源视频缺失，请在项目页重新关联同一视频') from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f'无法准备视频播放副本: {exc}') from exc


def _display_working_shot(shot: Shot, project: Project):
    video = project.video
    data = shot.model_dump()
    return shot_for_display(data, video.width, video.height) if video else data


@router.get("/shots")
def list_shots():
    project = _project_state
    return {"shots": [_display_working_shot(s, project) for s in project.shots], "video_source_id": _video_source_id(project)}


@router.get("/shots/{shot_id}")
def get_shot(shot_id: str, library_id: int | None = None):
    project = _project_state
    for shot in project.shots:
        if shot.shot_id == shot_id and (library_id is None or shot.library_id == library_id):
            return _display_working_shot(shot, project)
    raise HTTPException(status_code=404, detail="Shot not found")


@router.get("/shots/{shot_id}/frame/{frame_name}")
def get_shot_frame(shot_id: str, frame_name: str, library_id: int | None = None):
    if _project_state.video is None:
        raise HTTPException(status_code=400, detail="未导入视频")

    project_dir = _ensure_project_dirs(_project_state.project_name)
    frame_path = project_dir / "shots" / shot_id / frame_name
    matched = False
    for shot in _project_state.shots:
        if shot.shot_id == shot_id and (library_id is None or shot.library_id == library_id):
            matched = True
            if frame_name=='contact.jpg' and shot.frames:
                original=resolve_path(shot.frames[0])
                if original and original.is_file():
                    frame_path=original.parent/'contact.jpg'
            for frame in shot.frames:
                candidate = resolve_path(frame)
                if Path(frame).name == frame_name and candidate and candidate.is_file():
                    frame_path = candidate
                    break
            break
    if library_id is not None and not matched:
        raise HTTPException(status_code=404, detail="Library Shot not found")
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="帧文件不存在")

    return FileResponse(frame_path, media_type="image/jpeg")


@router.post("/shots/{shot_id}/analyze")
def analyze_shot(shot_id: str):
    raise HTTPException(status_code=501, detail="未实现")


@router.post("/export/json")
def export_json():
    output_path = _persist_project_state()
    data = _project_state.model_dump()
    return {"path": str(output_path), "data": data}


def _export_motion_script(shot: dict, width: int, height: int, fps: float, *, padded: bool = False):
    path = OUTPUT_DIR / 'ae_exports' / f'motion_{uuid4().hex}.jsx'
    try:
        export_ae_script(shot, width=width, height=height, fps=fps, path=path, padded=padded)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, '无法写入 AE 试作脚本，请检查导出目录') from exc
    return {'path': str(path.resolve()), 'message': '在 AE 中运行脚本会新建独立试作合成；请把 CONTENT 内容替换为静态素材。'}


@router.post('/shots/{shot_id}/export/ae')
@_exclusive_project_operation
def export_working_motion_script(shot_id: str, padded: bool = False):
    shot = next((s for s in _project_state.shots if s.shot_id == shot_id), None)
    if shot is None:
        raise HTTPException(404, '镜头不存在')
    video = _project_state.video
    if video is None:
        raise HTTPException(409, '视频元数据缺失，请重新导入')
    return _export_motion_script(shot.model_dump(), video.width, video.height, video.fps, padded=padded)


@router.post("/export/markdown")
def export_markdown():
    project_dir = _ensure_project_dirs(_project_state.project_name)
    output_path = project_dir / "report.md"

    lines = [f"# {_project_state.display_name or _project_state.project_name}", ""]
    if any(shot.provider_versions.get('vision',{}).get('provider')=='disabled' for shot in _project_state.shots):
        lines.append('基础分析已省略视觉、OCR 和排版语义模型；空字段不代表检测未发现。')
    if _project_state.video:
        v = _project_state.video
        lines.append(f"**视频**: {v.filename}")
        lines.append(f"**时长**: {v.duration}s")
        lines.append(f"**分辨率**: {v.width}x{v.height}")
        lines.append(f"**帧率**: {v.fps} fps")
        lines.append(f"**编码**: {v.codec}")
        lines.append("")

    lines.append(f"## 镜头（{len(_project_state.shots)}）")
    audio = _project_state.audio
    rhythm = _project_state.rhythm_summary
    lines.extend(['', '## 音频节奏（Rhythm）', f'- 音频状态: {audio.status} — {audio.message}',
                  f'- BPM（估计）: {audio.tempo_bpm if audio.tempo_bpm is not None else "不可用"}',
                  f'- 节拍 / 瞬态: {len(audio.beat_times)} / {len(audio.onset_times)}',
                  f'- 同步切镜: {rhythm.synced_cut_count}/{rhythm.measured_cut_count}（总切镜 {rhythm.cut_count}）',
                  f'- 同步容差: ±{rhythm.tolerance_ms:g}ms；正偏差=切镜晚于节拍，负偏差=早于节拍',
                  '- 节拍为算法估计，瞬态为声音事件；不代表作者的制作意图。', ''])
    if rhythm.excluded_shot_count:
        lines.append(f'- {rhythm.excluded_shot_count} 条旧镜头的时间原点未经确认，未参与节奏统计；请重新分析视频。')
    lines.append("")
    for shot in _project_state.shots:
        lines.append(f"### {shot.shot_id}")
        lines.append(f"- 时间: {shot.time.start}s - {shot.time.end}s (持续 {shot.time.duration}s)")
        timing = shot.rhythm
        if timing.delta_ms is not None:
            lines.append(f'- 切镜偏差: {timing.delta_ms:+.3f}ms；最近节拍 {timing.nearest_beat}s；同步: {timing.beat_sync}')
        else:
            lines.append(f'- 节奏: {timing.status}（无可用切镜节拍偏差）')
        if timing.message:
            lines.append(f'- 节奏说明: {timing.message}')
        lines.append(f"- 运动 (AI): {shot.motion.get('type', 'unknown')}")
        mm = shot.measured_motion
        if mm.sampling_target_fps is not None:
            lines.append(f"- 运动测量目标采样率：{mm.sampling_target_fps:g} 帧/秒")
        if has_global_totals(mm.status, mm.trajectory_status, mm.valid_pair_count):
            lines.append(
                f"- 运动 (CV): scale={mm.scale_change_percent:+.2f}%, "
                f"tx={mm.translation_x_ratio * 100:+.2f}%, "
                f"ty={mm.translation_y_ratio * 100:+.2f}%, "
                f"rot={mm.rotation_deg:.2f}°, "
                f"strength={mm.motion_strength}, conf={mm.confidence}"
            )
        else:
            reason = mm.message or '没有足够的连续帧对可计算整镜头位移'
            lines.append(f"- 整镜头运动测量不可用：{reason}（有效帧对 {mm.valid_pair_count}/{mm.total_pair_count}）")
        lines.append(f"- 主体: {shot.observations.get('subject_type', 'unknown')}")
        if shot.provider_versions.get('vision',{}).get('provider')=='disabled':
            lines.append('- 文字：基础分析未执行文字识别')
        else:
            lines.append(f"- 文字（视觉观察）：{'有' if shot.typography.get('has_text') else '无'}")
        lines.append("")

        if shot.typography_tracks:
            lines.append("#### 文字与排版")
            for track in shot.typography_tracks:
                lines.append(f"- 文字: {track.canonical_text}")
                lines.append(f"  - 用途: {(track.typography_analysis.role if track.typography_analysis else 'unknown')}")
                lines.append(f"  - 时间: {track.start_time:.2f}s → {track.end_time:.2f}s")
                avg = track.average_bbox
                lines.append(f"  - 位置: ({avg.x:.2f}, {avg.y:.2f}) / {avg.width:.2f}x{avg.height:.2f}")
                lines.append(f"  - 字体风格: {(track.typography_analysis.style_family if track.typography_analysis else 'unknown')} / {(track.typography_analysis.weight if track.typography_analysis else 'unknown')}")
                lines.append(f"  - 运动: {track.movement}")
                lines.append(f"  - AE 实现推测: {', '.join(track.ae_hypothesis) if track.ae_hypothesis else 'unknown'}")
                lines.append("")

        recipe = _display_working_shot(shot, _project_state)['ae_recipe']
        if recipe:
            lines.append("#### AE 制作建议")
            layers = recipe.get("layers", [])
            if layers:
                roles = [layer.get("role", "") for layer in layers]
                lines.append("- 分层建议: " + ", ".join(roles))
            camera = recipe.get("camera", {})
            if camera.get("type") not in (None, "unknown", "static"):
                lines.append(f"- 相机运动: {camera.get('type')} (强度 {camera.get('strength')})")
            effects = recipe.get("effects", [])
            if effects:
                lines.append("- 可能效果: " + ", ".join(effects))
            plan = recipe.get('animation_plan', {})
            lines.extend(animation_plan_markdown(plan))
            difficulty = recipe.get("difficulty", {})
            if difficulty:
                lines.append(f"- 难度: {difficulty.get('ae', '未知')}")
            lines.append("")

    md = "\n".join(lines)
    output_path.write_text(md, encoding="utf-8")
    return {"path": str(output_path), "markdown": md}


# ---------------------------------------------------------------------------
# Reference Library endpoints (Milestone 5)
# ---------------------------------------------------------------------------


@router.get("/library/projects")
def list_library_projects():
    """List all persisted projects."""
    try:
        lib = _get_library()
        projects = lib.list_projects()
        return {
            "projects": [
                LibraryProjectSummary(
                    id=p.id,
                    name=p.display_name or p.name,
                    video_filename=p.video_filename,
                    video_duration=p.video_duration,
                    analysis_status=p.analysis_status,
                    updated_at=p.updated_at,
                ).model_dump()
                for p in projects
            ]
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.get("/library/projects/{project_id}")
def get_library_project(project_id: int):
    """Load a project and its shots from the library."""
    try:
        lib = _get_library()
        project, shots = lib.load_project(project_id)
        return {
            "project": LibraryProjectSummary(
                id=project.id,
                name=project.display_name or project.name,
                video_filename=project.video_filename,
                video_duration=project.video_duration,
                analysis_status=project.analysis_status,
                updated_at=project.updated_at,
            ).model_dump(),
            "shots": [
                LibraryShotSummary(
                    id=s.id,
                    project_id=s.project_id,
                    shot_id=s.shot_id,
                    start_time=s.start_time,
                    end_time=s.end_time,
                    duration=s.duration,
                    thumbnail_path=s.thumbnail_path,
                    motion_type=s.motion_type,
                    has_text=s.has_text,
                    tags=s.tags,
                ).model_dump()
                for s in shots
            ],
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.post("/library/projects/{project_id}/load")
@_exclusive_project_operation
def load_project_into_memory(project_id: int):
    """Load a persisted project back into the in-memory working state."""
    global _project_state
    try:
        lib = _get_library()
        project, shots = lib.load_project(project_id)
        _project_state = Project(
            project_name=project.name,
            display_name=project.display_name,
            video_path=project.video_path,
            source_hash=project.video_hash if project.video_hash and not project.video_hash.startswith('legacy:') else '',
            assets_dir=str(resolve_path(project.assets_dir)) if project.assets_dir else None,
            analysis_status=project.analysis_status,
            analysis_message=project.analysis_message,
            library_project_id=project.id,
            audio=project.audio,
            rhythm_summary=project.rhythm_summary,
        )
        if project.video_filename:
            _project_state.video = VideoInfo(
                filename=project.video_filename,
                duration=project.video_duration,
                width=project.video_width,
                height=project.video_height,
                fps=project.video_fps,
                codec=project.video_codec,
                has_audio=project.video_has_audio,
            )
        from projects.session import SessionState, write_session
        write_session(SessionState(project_id=project.id))
        with lib._conn:
            lib._conn.execute("UPDATE projects SET last_opened_at=datetime('now') WHERE id=?",(project.id,))
        if _project_state.analysis_status=='processing':
            _project_state.analysis_status='completed_with_warnings'
            _project_state.analysis_message='上次分析已中断，可重新分析'
        # Convert LibraryShot rows back to Pydantic Shot instances
        _project_state.shots = [
            Shot(
                shot_id=s.shot_id,
                library_id=s.id,
                time=TimeRange(start=s.start_time, end=s.end_time, duration=s.duration),
                frames=s.frame_paths,
                observations=s.observations,
                motion=s.motion,
                measured_motion=s.measured_motion,
                motion_summary=s.motion_summary,
                rhythm=s.rhythm,
                typography=s.typography,
                text_regions=s.text_regions,
                typography_tracks=s.typography_tracks,
                ae_hypothesis=s.ae_hypothesis,
                ae_recipe=s.ae_recipe,
                visual_effects=s.visual_effects,
                analysis_error=s.analysis_error,
                analysis_version=s.analysis_version,
                pipeline_version=s.pipeline_version,
                provider_versions=s.provider_versions,
            )
            for s in shots
        ]
        return {"status": "ok", "shot_count": len(_project_state.shots)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.delete("/library/projects/{project_id}")
def delete_library_project(project_id: int):
    """Delete a project and all its shots from the library."""
    try:
        lib = _get_library()
        if not lib.delete_project(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.get("/library/shots")
def list_library_shots(project_id: int | None = None):
    """List shots across all projects or a specific project."""
    try:
        lib = _get_library()
        if project_id is not None:
            shots = lib.list_shots(project_id)
        else:
            shots = lib.search(FilterSet(limit=1000))
        return {
            "shots": [
                LibraryShotSummary(
                    id=s.id,
                    project_id=s.project_id,
                    shot_id=s.shot_id,
                    start_time=s.start_time,
                    end_time=s.end_time,
                    duration=s.duration,
                    thumbnail_path=s.thumbnail_path,
                    motion_type=s.motion_type,
                    has_text=s.has_text,
                    tags=s.tags,
                ).model_dump()
                for s in shots
            ]
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.post("/shots/{shot_id}/tags")
def set_shot_tags(shot_id: str, body: ShotTagsUpdate):
    """Set tags for a shot in the current project."""
    try:
        lib = _get_library()
        project_id = lib.save_project(_project_state)
        if not lib.set_shot_tags(project_id, shot_id, body.tags):
            raise HTTPException(status_code=404, detail="Shot not found")
        return {"status": "ok", "tags": body.tags}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.post("/shots/{shot_id}/tags/{tag_name}")
def add_shot_tag(shot_id: str, tag_name: str):
    """Add a single tag to a shot."""
    try:
        lib = _get_library()
        project_id = lib.save_project(_project_state)
        if not lib.tag_shot(project_id, shot_id, tag_name):
            raise HTTPException(status_code=404, detail="Shot not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.delete("/shots/{shot_id}/tags/{tag_name}")
def remove_shot_tag(shot_id: str, tag_name: str):
    """Remove a single tag from a shot."""
    try:
        lib = _get_library()
        project_id = lib.save_project(_project_state)
        if not lib.untag_shot(project_id, shot_id, tag_name):
            raise HTTPException(status_code=404, detail="Shot or tag not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.get("/tags")
def list_tags():
    """List all known tags."""
    try:
        lib = _get_library()
        tags = lib.list_tags()
        return {"tags": [TagResponse(id=t.id, name=t.name, color=t.color).model_dump() for t in tags]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.post("/tags")
def create_tag(body: TagCreate):
    """Create a new tag."""
    try:
        lib = _get_library()
        tag = lib._tags.ensure(body.name, body.color)
        return TagResponse(id=tag.id, name=tag.name, color=tag.color).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.post("/search")
def search_library(body: FilterRequest):
    """Search and filter shots across the library."""
    try:
        lib = _get_library()
        filters = FilterSet(**body.model_dump())
        shots = lib.search(filters)
        return LibrarySearchResponse(
            shots=[
                LibraryShotSummary(
                    id=s.id,
                    project_id=s.project_id,
                    shot_id=s.shot_id,
                    start_time=s.start_time,
                    end_time=s.end_time,
                    duration=s.duration,
                    thumbnail_path=s.thumbnail_path,
                    motion_type=s.motion_type,
                    has_text=s.has_text,
                    tags=s.tags,
                    motion_confidence=s.motion_confidence,
                    scene_type=s.scene_type,
                )
                for s in shots
            ],
            motion_types=lib.unique_motion_types(),
        ).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Library error: {exc}") from exc


@router.post("/library/save")
@_exclusive_project_operation
def save_to_library():
    if not _project_state.shots:
        raise HTTPException(status_code=400, detail="没有可保存的分析结果")
    if not _persist_to_library(raise_identity_conflict=True):
        raise HTTPException(status_code=503, detail=_project_state.library_warning)
    _persist_project_state()
    return {"status": "ok", "project_id": _project_state.library_project_id}


def _library_shot(db_id: int):
    try:
        return _get_library().get_shot(db_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Library error: {exc}") from exc


@router.get("/library/shots/{db_id}")
def library_shot_detail(db_id: int):
    shot = _library_shot(db_id)
    project = _get_library().get_project(shot.project_id)
    timestamps = (shot.provider_versions.get('representative_frames') or {}).get('timestamps', [])
    return {**shot_for_display(asdict(shot), project.video_width, project.video_height),
            'frame_timestamps': timestamps, "source": asdict(project)}


@router.get("/library/shots/{db_id}/thumbnail")
def library_thumbnail(db_id: int):
    shot = _library_shot(db_id)
    path = resolve_path(shot.thumbnail_path)
    if path is None or not path.is_file():
        project = _get_library().get_project(shot.project_id)
        path = OUTPUT_DIR / project.name / "shots" / shot.shot_id / Path(shot.thumbnail_path or '').name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="缩略图文件不存在")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/library/shots/{db_id}/source")
def library_source(db_id: int):
    shot = _library_shot(db_id)
    project = _get_library().get_project(shot.project_id)
    return _verified_playback(resolve_path(project.video_path), project.video_hash)


@router.get("/library/shots/{db_id}/recipe")
def library_recipe(db_id: int):
    return library_shot_detail(db_id)['ae_recipe']


@router.post("/library/shots/{db_id}/export/recipe")
def export_library_recipe(db_id: int):
    recipe = library_recipe(db_id)
    directory = OUTPUT_DIR / 'library_exports' / str(db_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'shot_{db_id}_recipe.json'
    path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'path': str(path.resolve())}


@router.post('/library/shots/{db_id}/export/ae')
def export_library_motion_script(db_id: int, padded: bool = False):
    shot = _library_shot(db_id)
    project = _get_library().get_project(shot.project_id)
    data = {**asdict(shot), 'time': {'start': shot.start_time, 'end': shot.end_time,
                                    'duration': shot.duration}}
    return _export_motion_script(data, project.video_width, project.video_height, project.video_fps, padded=padded)


@router.put("/library/shots/{db_id}/tags")
def library_manual_tags(db_id: int, body: ShotTagsUpdate):
    _library_shot(db_id)
    _get_library().set_manual_tags_by_id(db_id, body.tags)
    return library_shot_detail(db_id)


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int):
    if not _get_library()._tags.delete(tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"status": "ok"}
