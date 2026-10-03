import json
import logging
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from threading import Lock, RLock
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from app.config import get_config
from app.progress import AnalysisProgressTracker
from app.runtime_paths import get_runtime_paths
from audio.analyzer import analyze_audio
from audio.cache import AudioCache
from audio.rhythm import VIDEO_CLOCK_VERSION, apply_rhythm
from cv import MotionCache, analyze_shot_motion, fuse_motion
from db import ReferenceLibrary
from db.models import FilterSet
from db.paths import resolve_path, video_hash
from ocr import OCRCache, ShotOCRAnalyzer, create_ocr_provider
from ocr.semantic import TypographyCache, TypographySemanticAnalyzer
from recipe.ae_recipe import generate_ae_recipe
from recipe.difficulty import estimate_difficulty
from schemas import (
    AnalysisProgress,
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
from schemas.audio import AudioAnalysis, RhythmSummary
from video.frame_sampler import create_contact_sheet, sample_frames
from video.metadata import read_video_metadata
from video.playback import playback_source
from video.scene_detect import detect_scenes
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


def _ensure_project_dirs(project_name: str) -> Path:
    project_dir = (resolve_path(_project_state.assets_dir)
                   if _project_state.project_name == project_name and _project_state.assets_dir
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
    video_path = Path(req.path)
    if not video_path.exists():
        _project_state.analysis_status = "error"
        _project_state.analysis_message = f"视频文件不存在: {video_path}"
        raise HTTPException(status_code=404, detail=_project_state.analysis_message)

    metadata = read_video_metadata(video_path)
    _project_state.video = VideoInfo(**metadata)
    _project_state.video_path = str(video_path.resolve())
    _project_state.project_name = f"{video_path.stem}_{video_hash(video_path)[:8]}"
    _project_state.assets_dir = str((OUTPUT_DIR / _project_state.project_name).resolve())
    _project_state.library_warning = ""
    _project_state.library_project_id = None
    _project_state.display_name = ''
    _project_state.shots = []
    _project_state.audio = AudioAnalysis()
    _project_state.rhythm_summary = RhythmSummary()
    _project_state.analysis_status = "imported"
    _project_state.analysis_message = ""
    _project_state.progress = AnalysisProgress()

    return {
        "status": "ok",
        "video": _project_state.video.model_dump(),
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


def _persist_to_library() -> bool:
    """将当前项目状态和 Shots 持久化到 SQLite Reference Library。"""
    try:
        lib = _get_library()
        _project_state.library_project_id = lib.save_analysis(_project_state)
        _project_state.library_warning = ""
        from projects.session import SessionState, write_session
        write_session(SessionState(project_id=_project_state.library_project_id))
        return True
    except Exception as exc:
        logging.getLogger(__name__).warning("保存到 Reference Library 失败: %s", exc)
        _project_state.library_warning = f"Reference Library 保存失败，可重试: {exc}"
        return False


def _analyze_project_audio(video_path: Path, force: bool = False) -> AudioAnalysis:
    config = get_config()
    try:
        result = analyze_audio(video_path, sample_rate=config.audio_sample_rate,
                               hop_length=config.audio_hop_length, max_duration=config.audio_max_duration,
                               cache=AudioCache(config.audio_cache_dir), force=force)
    except Exception as exc:
        result = AudioAnalysis(status='error', message=f'音频分析失败: {exc}')
    _project_state.audio = result
    _project_state.rhythm_summary = apply_rhythm(_project_state.shots, result, config.beat_sync_tolerance_ms)
    for shot in _project_state.shots:
        shot.provider_versions['audio'] = {'method': result.method, 'librosa': result.library_version}
    return result


class AudioAnalyzeRequest(BaseModel):
    force: bool = False


@router.post('/video/analyze-audio')
@_exclusive_project_operation
def analyze_project_audio(req: AudioAnalyzeRequest | None = None):
    """Retry only audio, reusing the current cuts and preserving all other analyses."""
    result = _analyze_project_audio(_resolve_video_path(), force=bool(req and req.force))
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
    tracker = AnalysisProgressTracker(_project_state)

    if _project_state.video is None or _project_state.video_path is None:
        tracker.set_error("preparing", "未导入视频")
        raise HTTPException(status_code=400, detail=_project_state.analysis_message)

    tracker.start_analysis()

    has_warnings = False

    try:
        config = get_config()
        basic=bool(req and req.mode=='basic')
        if not basic and config.ocr_provider=='paddleocr':
            from models.ocr_paths import validate_ocr_models
            validation=validate_ocr_models(config.ocr_models)
            if not validation.available:
                raise HTTPException(409,'；'.join(validation.errors))
        video_path = _resolve_video_path()
        if _project_state.library_project_id:
            known=_get_library().get_project(_project_state.library_project_id)
            if known.video_hash and not known.video_hash.startswith('legacy:') and video_hash(video_path)!=known.video_hash:
                raise HTTPException(409,'源视频内容已改变，请重新导入为新项目')
        if not basic and config.vision_provider != 'mock':
            from models.ollama import OllamaInspector
            models=OllamaInspector(config.qwen_api_base).inspect()
            if not any(m['id']==config.qwen_model_id and m['vision'] for m in models['models']):
                raise HTTPException(409,'视觉模型未就绪，请在模型页配置，或选择基础分析')
        # Each run owns its assets; archived ranges/versions must keep their frames.
        _project_state.assets_dir = str((OUTPUT_DIR / _project_state.project_name /
                                         'runs' / uuid4().hex).resolve())
        project_dir = _ensure_project_dirs(_project_state.project_name)

        # 1. 分镜
        tracker.start_stage("scene_detect", "正在检测镜头切换")
        shots_meta = detect_scenes(video_path)
        tracker.complete_stage("scene_detect")

        # 2. 代表帧提取与 Contact Sheet
        tracker.start_stage("extract_frames", "正在提取代表帧")
        shots = []

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
                pipeline_version='mra-pipeline-v2-video-clock',
                provider_versions={'video_clock': {'version': VIDEO_CLOCK_VERSION}},
            )
            shots.append(shot)

        _project_state.shots = shots
        tracker.complete_stage("extract_frames")

        total_shots = len(_project_state.shots)

        tracker.start_stage('audio_analysis', '正在检测音频节拍与瞬态')
        audio_result = _analyze_project_audio(video_path)
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

            for idx, shot in enumerate(_project_state.shots, start=1):
                try:
                    analysis = analyzer.analyze(
                        shot,
                        project_dir,
                        video_filename=_project_state.video.filename,
                    )
                    if analysis.analysis_error:
                        raise RuntimeError(analysis.analysis_error)
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
            for shot in _project_state.shots:
                shot.provider_versions['vision']=model_info

        # 4. CV 运动测量
        tracker.start_stage("cv_analysis", "正在测量全局运动")
        cv_cache = MotionCache(config.cv_cache_dir)
        for idx, shot in enumerate(_project_state.shots, start=1):
            try:
                cached = cv_cache.get(
                    video_path,
                    shot.time.start,
                    shot.time.end,
                    config.cv_target_fps,
                    config.cv_max_long_edge,
                )
                if cached is not None:
                    shot.measured_motion = cached
                else:
                    measured = analyze_shot_motion(
                        video_path,
                        shot.time.start,
                        shot.time.end,
                        original_width=_project_state.video.width,
                        original_height=_project_state.video.height,
                        target_fps=config.cv_target_fps,
                        max_long_edge=config.cv_max_long_edge,
                    )
                    shot.measured_motion = measured
                    cv_cache.set(
                        video_path,
                        shot.time.start,
                        shot.time.end,
                        measured,
                        config.cv_target_fps,
                        config.cv_max_long_edge,
                    )

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
            for shot in _project_state.shots:
                shot.provider_versions.update({"vision": model_info, "ocr": ocr_provider.get_model_info()})
            ocr_cache = OCRCache(config.ocr_cache_dir)
            ocr_analyzer = ShotOCRAnalyzer(
                provider=ocr_provider,
                cache=ocr_cache,
                target_fps=config.ocr_target_fps,
                min_frames=config.ocr_min_frames,
                max_frames=config.ocr_max_frames,
                max_long_edge=config.ocr_max_long_edge,
            )

            for idx, shot in enumerate(_project_state.shots, start=1):
                try:
                    ocr_result = ocr_analyzer.analyze(
                        video_path,
                        shot.time.start,
                        shot.time.end,
                    )
                    if ocr_result.analysis_error:
                        raise RuntimeError(ocr_result.analysis_error)
                    shot.text_regions = ocr_result.text_regions
                    shot.typography_tracks = ocr_result.typography_tracks
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

            for idx, shot in enumerate(_project_state.shots, start=1):
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
            for shot in _project_state.shots:
                shot.provider_versions['ocr']={'provider':'disabled','reason':'basic'}
                shot.provider_versions['typography']={'provider':'disabled','reason':'basic'}

        # 7. Recipe 生成
        tracker.start_stage("recipe_generation", "正在生成 AE Recipe")
        for idx, shot in enumerate(_project_state.shots, start=1):
            try:
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
        tracker.set_error('preparing',str(exc.detail))
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


@router.get("/project/status")
def project_status():
    return {
        "status": _project_state.analysis_status,
        "project_name": _project_state.display_name or _project_state.project_name,
        "message": _project_state.analysis_message,
        "video": _project_state.video.model_dump() if _project_state.video else None,
        "video_path": _project_state.video_path,
        "shot_count": len(_project_state.shots),
        "progress": _project_state.progress.model_dump_safe(),
        "library_warning": _project_state.library_warning,
        "library_project_id": _project_state.library_project_id,
        "audio": _project_state.audio.model_dump(),
        "rhythm_summary": _project_state.rhythm_summary.model_dump(),
    }


@router.get('/video/source')
def project_video_source():
    """Serve the current source with FileResponse Range support for rhythm inspection."""
    source = _resolve_video_path()
    try:
        return FileResponse(playback_source(source, OUTPUT_DIR / 'playback_cache'), media_type='video/mp4')
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f'无法准备视频播放副本: {exc}') from exc


@router.get("/shots")
def list_shots():
    return {"shots": [s.model_dump() for s in _project_state.shots]}


@router.get("/shots/{shot_id}")
def get_shot(shot_id: str, library_id: int | None = None):
    for shot in _project_state.shots:
        if shot.shot_id == shot_id and (library_id is None or shot.library_id == library_id):
            return shot.model_dump()
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
        if mm.status == "ok":
            lines.append(
                f"- 运动 (CV): scale={mm.scale_change_percent:+.2f}%, "
                f"tx={mm.translation_x_ratio * 100:+.2f}%, "
                f"ty={mm.translation_y_ratio * 100:+.2f}%, "
                f"rot={mm.rotation_deg:.2f}°, "
                f"strength={mm.motion_strength}, conf={mm.confidence}"
            )
        else:
            lines.append(f"- 运动 (CV): {mm.status} - {mm.message}")
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

        recipe = shot.ae_recipe
        if recipe:
            lines.append("#### AE 制作建议")
            layers = recipe.get("layers", [])
            if layers:
                roles = [layer.get("role", "") for layer in layers]
                lines.append("- 分层建议: " + ", ".join(roles))
            camera = recipe.get("camera", {})
            if camera.get("type") != "static":
                lines.append(f"- 相机运动: {camera.get('type')} (强度 {camera.get('strength')})")
            effects = recipe.get("effects", [])
            if effects:
                lines.append("- 可能效果: " + ", ".join(effects))
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
    if not _persist_to_library():
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
    return {**asdict(shot), "source": asdict(project)}


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
    path = resolve_path(project.video_path)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="源视频已移动或不存在")
    try:
        return FileResponse(playback_source(path, OUTPUT_DIR / 'playback_cache'), media_type='video/mp4')
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f'无法准备视频播放副本: {exc}') from exc


@router.get("/library/shots/{db_id}/recipe")
def library_recipe(db_id: int):
    return _library_shot(db_id).ae_recipe


@router.post("/library/shots/{db_id}/export/recipe")
def export_library_recipe(db_id: int):
    shot = _library_shot(db_id)
    directory = OUTPUT_DIR / 'library_exports' / str(db_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'shot_{db_id}_recipe.json'
    path.write_text(json.dumps(shot.ae_recipe, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'path': str(path.resolve())}


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
