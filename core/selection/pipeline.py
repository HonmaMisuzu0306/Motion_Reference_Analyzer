"""Run on a private snapshot and write only the independent record's assets."""
import hashlib
import json
from pathlib import Path

from PIL import Image

from audio.rhythm import apply_rhythm
from cv import analyze_shot_motion, fuse_motion
from cv.cache import CV_ALGORITHM_VERSION
from ocr import OCRCache, ShotOCRAnalyzer, create_ocr_provider
from ocr.semantic import TypographyCache, TypographySemanticAnalyzer
from recipe.ae_recipe import generate_ae_recipe
from recipe.keyframes import RECIPE_VERSION
from schemas import Shot
from selection.blend import MAX_SECONDS, METHOD, BlendSamples
from selection.frames import locate_frame
from selection.media import analyze_range_audio, detect_range_scenes, sample_range_frames
from selection.models import JobSnapshot
from selection.static import STATIC_PROMPT_VERSION, StaticVisionAnalysis, static_recipe
from video.scene_features import SCENE_DETECT_VERSION
from vision.analyzer import ShotAnalyzer, update_shot_with_analysis
from vision.cache import VisionCache
from vision.factory import create_vision_provider
from vision.prompts import PROMPT_VERSION

PIPELINE_VERSION = 'selection-pipeline-v7-two-held-pictures'


def _cache_root(snapshot, versions):
    identity = {'kind': snapshot.request.kind, 'source_hash': snapshot.source_hash,
                'frame': snapshot.request.frame.model_dump() if snapshot.request.frame else None,
                'start': snapshot.request.start, 'end': snapshot.request.end,
                'versions': versions, 'sampling': 'actual-pts-half-open-v1'}
    identity['model_identity'] = snapshot.model_identity
    identity['config'] = snapshot.config.model_dump(mode='json')
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    root = Path(snapshot.config.vision_cache_dir) / 'selection' / digest
    root.mkdir(parents=True, exist_ok=True)
    return root


def _save(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame.image[:, :, ::-1]).save(path)


def _measure_clip(snapshot, result, report):
    start, end = snapshot.request.start, snapshot.request.end
    result['time'] = {'start': start, 'end': end, 'duration': end - start}
    report('scenes', 0, 1, '检查选区内的切镜与叠化')
    blend = BlendSamples() if end - start <= MAX_SECONDS else None
    dedicated = snapshot.request.measurement == 'opacity_blend'
    ranges = detect_range_scenes(snapshot.source_path, start, end, blend, review_boundary=dedicated)
    if blend is not None and (len(ranges) == 1 or (dedicated and len(ranges) == 2)):
        boundary = ranges[1].start if len(ranges) == 2 else None
        estimate = blend.estimate(end, boundary=boundary)
        if estimate is not None:
            result['opacity_blend'] = estimate
        elif dedicated and boundary is not None:
            result['measurement_message'] = blend.skip_message or '选区中检测到切镜。请缩短到一次连续过渡。'
        elif dedicated:
            result['measurement_message'] = blend.skip_message or (
                '未取得可靠的全画面混合曲线。请选取一次叠化，并在两端各保留至少 0.15 秒静止画面。')
    elif snapshot.request.measurement:
        result['measurement_message'] = '选区中检测到切镜。请缩短到一次连续过渡。'
    return ranges


def run_selection(snapshot: JobSnapshot, report) -> dict:
    config, assets, request = snapshot.config, snapshot.assets_dir, snapshot.request
    assets.mkdir(parents=True, exist_ok=True)
    if request.measurement == 'opacity_blend':
        result = {'schema_version': 1, 'kind': 'clip', 'source_hash': snapshot.source_hash,
                  'measurement': request.measurement, 'versions': {'pipeline': PIPELINE_VERSION, 'opacity_blend': METHOD},
                  'warnings': [], 'partial_failures': []}
        _measure_clip(snapshot, result, report)
        report('saving', 1, 1, '保存叠化测量')
        return result
    provider, ocr = create_vision_provider(config), create_ocr_provider(config)
    versions = {'pipeline': PIPELINE_VERSION, 'vision': provider.get_model_info(), 'ocr': ocr.get_model_info(),
                'prompt': STATIC_PROMPT_VERSION if request.kind == 'frame' else PROMPT_VERSION,
                'video_clock': {'version': 'video-relative-v1'}, 'sampling': 'actual-pts-half-open-v1'}
    versions['model_identity'] = snapshot.model_identity
    if request.kind == 'clip':
        versions['opacity_blend'] = METHOD
        versions['scene_detection'] = SCENE_DETECT_VERSION
        versions['recipe'] = RECIPE_VERSION
        versions['cv'] = {'version': CV_ALGORITHM_VERSION, 'target_fps': config.cv_target_fps,
                          'max_long_edge': config.cv_max_long_edge}
    cache_root = _cache_root(snapshot, versions)
    warnings, partial_failures = [], []
    result = {'schema_version': 1, 'kind': request.kind, 'source_hash': snapshot.source_hash,
              'versions': versions, 'warnings': warnings, 'partial_failures': partial_failures}
    if request.kind == 'frame':
        report('frame', 0, 1, '定位并保存准确单帧')
        frame = locate_frame(snapshot.source_path, request.frame.requested_time, pts=request.frame.pts)
        if frame.identity != request.frame:
            raise ValueError('源帧身份已改变，请重新定位')
        image = assets / 'frame.png'
        _save(frame, image)
        result['time'] = frame.identity.model_dump()
        report('vision', 0, 1, '分析静态构图与可见效果')
        cached_file = cache_root / 'static.json'
        analysis = None
        try:
            analysis = StaticVisionAnalysis.model_validate_json(cached_file.read_text(encoding='utf-8'))
            if analysis.analysis_error:
                analysis = None
        except (OSError, ValueError):
            pass
        if analysis is None:
            analysis = provider.analyze_static_frame(image, result['time'])
            if not analysis.analysis_error:
                try:
                    cached_file.write_text(analysis.model_dump_json(), encoding='utf-8')
                except OSError:
                    warnings.append('缓存写入失败，分析结果仍可保存')
        if analysis.analysis_error:
            warnings.append(analysis.analysis_error)
            partial_failures.append(analysis.analysis_error)
        report('ocr', 0, 1, '识别当前单帧文字')
        regions = []
        try:
            if ocr.get_model_info().get('available') is False:
                raise RuntimeError(ocr.get_model_info().get('error_message', 'OCR不可用'))
            h, w = frame.image.shape[:2]
            regions = ocr.analyze_frame(frame.image, frame_timestamp=frame.identity.actual_time,
                                        frame_width=w, frame_height=h)
            for region in regions:
                region.frame_timestamp = frame.identity.actual_time
        except Exception as exc:
            warnings.append(f'单帧OCR失败：{exc}')
            partial_failures.append(f'单帧OCR失败：{exc}')
            if analysis.analysis_error:
                raise RuntimeError('视觉模型和OCR均失败，没有可交付的模型分析结果') from exc
        result['frame'] = {**analysis.model_dump(), 'image': 'frame.png',
                           'text_regions': [r.model_dump() for r in regions],
                           'ae_recipe': static_recipe(analysis, regions)}
        warnings.append('单帧仅分析静态信息；运动、转场、动画和节奏不适用')
    else:
        ranges = _measure_clip(snapshot, result, report)
        shots, identities, static_analyses = [], {}, {}
        analyzer = ShotAnalyzer(provider, VisionCache(cache_root / 'vision'), config.vision_max_retries)
        ocr_analyzer = ShotOCRAnalyzer(ocr, OCRCache(cache_root / 'ocr'), config.ocr_target_fps,
                                       config.ocr_min_frames, config.ocr_max_frames,
                                       config.ocr_max_long_edge, strict_range=True)
        typography = TypographySemanticAnalyzer(provider, TypographyCache(cache_root / 'typography'),
                                                 config.typography_max_tracks_per_shot,
                                                 config.typography_confidence_threshold, config.vision_max_retries)
        for i, time in enumerate(ranges, 1):
            shot = Shot(shot_id=f'shot_{i:03d}', time=time, pipeline_version=PIPELINE_VERSION,
                        provider_versions=versions)
            report('shots', i - 1, len(ranges), f'分析局部镜头 {i}/{len(ranges)}')
            frames = sample_range_frames(snapshot.source_path, time.start, time.end, 3)
            if not frames:
                raise ValueError('局部镜头没有可解码帧')
            identities[shot.shot_id] = [f.identity.model_dump() for f in frames]
            for j, frame in enumerate(frames, 1):
                name = f'frame_{j:02d}.png'
                _save(frame, assets / 'shots' / shot.shot_id / name)
                shot.frames.append(name)
            only_one_frame = len(frames) == 1
            stages = [
                ('vision', lambda: _vision(shot, analyzer, assets, snapshot.source_path.name)),
                ('cv', lambda: _motion(shot, snapshot.source_path, config, frames[0].image.shape)),
                ('ocr', lambda: _ocr(shot, ocr_analyzer, snapshot.source_path)),
                ('typography', lambda: typography.analyze_tracks(
                    shot.typography_tracks, assets / 'shots' / shot.shot_id / shot.frames[0],
                    shot.shot_id, video_path=snapshot.source_path)),
            ]
            if only_one_frame:
                note = f'{shot.shot_id}仅包含一张实际画面；运动、转场和文字动画证据不足，改为静态分析'
                warnings.append(note)
                partial_failures.append(note)
                def static_vision():
                    analysis = provider.analyze_static_frame(assets / 'shots' / shot.shot_id / shot.frames[0], identities[shot.shot_id][0])
                    if analysis.analysis_error:
                        raise RuntimeError(analysis.analysis_error)
                    static_analyses[shot.shot_id] = analysis
                    shot.observations = analysis.observations.model_dump()
                    shot.typography = analysis.typography.model_dump()
                    shot.visual_effects = [effect.model_dump() for effect in analysis.visual_effects]
                    shot.ae_hypothesis = analysis.ae_hypothesis.model_dump()
                stages = [('vision', static_vision), ('ocr', lambda: _ocr(shot, ocr_analyzer, snapshot.source_path))]
            for stage, operation in stages:
                report(stage, i - 1, len(ranges), f'局部镜头 {i}/{len(ranges)}：{stage}')
                try:
                    operation()
                except Exception as exc:
                    message = f'{shot.shot_id} {stage}：{exc}'
                    warnings.append(message)
                    partial_failures.append(message)
                    shot.analysis_error += message + '\n'
            for track in shot.typography_tracks:
                if track.typography_analysis and track.typography_analysis.analysis_error:
                    message = f'{shot.shot_id}文字语义：{track.typography_analysis.analysis_error}'
                    warnings.append(message)
                    partial_failures.append(message)
            if only_one_frame:
                # A track from one timestamp provides no temporal evidence.
                shot.typography_tracks = []
            shots.append(shot)
        report('audio', 0, 1, '分析选区音频与切镜节奏')
        audio = analyze_range_audio(snapshot.source_path, request.start, request.end,
                                     sample_rate=config.audio_sample_rate, hop_length=config.audio_hop_length)
        rhythm = apply_rhythm(shots, audio, config.beat_sync_tolerance_ms)
        if audio.status != 'ok':
            warnings.append(audio.message)
        for shot in shots:
            shot.ae_recipe = (static_recipe(static_analyses.get(shot.shot_id, StaticVisionAnalysis()), shot.text_regions)
                              if len(identities[shot.shot_id]) == 1 else generate_ae_recipe(shot.model_dump()))
        result.update(shots=[{**s.model_dump(), 'frame_identities': identities[s.shot_id]} for s in shots],
                      audio=audio.model_dump(), rhythm_summary=rhythm.model_dump())
    report('saving', 1, 1, '保存独立分析记录')
    return result


def _vision(shot, analyzer, assets, filename):
    analysis = analyzer.analyze(shot, assets, filename)
    if analysis.analysis_error:
        raise RuntimeError(analysis.analysis_error)
    update_shot_with_analysis(shot, analysis)


def _motion(shot, path, config, shape):
    shot.measured_motion = analyze_shot_motion(path, shot.time.start, shot.time.end,
                                               original_width=shape[1], original_height=shape[0],
                                               target_fps=config.cv_target_fps, max_long_edge=config.cv_max_long_edge)
    shot.motion_summary = fuse_motion(shot.motion, shot.measured_motion)


def _ocr(shot, analyzer, path):
    analysis = analyzer.analyze(path, shot.time.start, shot.time.end)
    if analysis.analysis_error:
        raise RuntimeError(analysis.analysis_error)
    shot.text_regions, shot.typography_tracks = analysis.text_regions, analysis.typography_tracks
