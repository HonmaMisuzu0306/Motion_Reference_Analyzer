import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from recipe.ae_recipe import generate_ae_recipe
from recipe.difficulty import estimate_difficulty
from schemas import Project, Shot, TimeRange, VideoInfo
from video.frame_sampler import create_contact_sheet, sample_frames
from video.metadata import read_video_metadata
from video.scene_detect import detect_scenes

router = APIRouter()

# MVP 阶段使用内存存储项目状态
_project_state: Project = Project()

# 输出目录
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


def _ensure_project_dirs(project_name: str) -> Path:
    project_dir = OUTPUT_DIR / project_name
    (project_dir / "shots").mkdir(parents=True, exist_ok=True)
    (project_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (project_dir / "thumbnails").mkdir(parents=True, exist_ok=True)
    return project_dir


class VideoImportRequest(BaseModel):
    path: str


@router.post("/video/import")
def import_video(req: VideoImportRequest):
    video_path = Path(req.path)
    if not video_path.exists():
        _project_state.analysis_status = "error"
        _project_state.analysis_message = f"视频文件不存在: {video_path}"
        raise HTTPException(status_code=404, detail=_project_state.analysis_message)

    metadata = read_video_metadata(video_path)
    _project_state.video = VideoInfo(**metadata)
    _project_state.video_path = str(video_path.resolve())
    _project_state.project_name = video_path.stem
    _project_state.shots = []
    _project_state.analysis_status = "imported"
    _project_state.analysis_message = ""

    return {
        "status": "ok",
        "video": _project_state.video.model_dump(),
    }


@router.post("/video/analyze")
def analyze_video():
    if _project_state.video is None or _project_state.video_path is None:
        _project_state.analysis_status = "error"
        _project_state.analysis_message = "未导入视频"
        raise HTTPException(status_code=400, detail=_project_state.analysis_message)

    _project_state.analysis_status = "processing"
    _project_state.analysis_message = ""

    try:
        # 1. 分镜
        _project_state.analysis_status = "scene_detect"
        video_path = _resolve_video_path()
        shots_meta = detect_scenes(video_path)

        # 2. 代表帧提取与 Contact Sheet
        _project_state.analysis_status = "extract_frames"
        project_dir = _ensure_project_dirs(_project_state.project_name)
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
                Image.fromarray(frame_info["image"]).save(frame_path, quality=90)
                frame_files.append(frame_path.name)
                frames.append(frame_info["image"])

            contact_path = shot_dir / "contact.jpg"
            create_contact_sheet(frames, contact_path)

            shot = Shot(
                shot_id=shot_id,
                time=TimeRange(**meta),
                frames=frame_files,
            )
            shots.append(shot)

        _project_state.shots = shots

        # 3. VLM 分析（占位，下一版接入）
        _project_state.analysis_status = "vision_analysis"
        for shot in _project_state.shots:
            shot.observations = {"subject_type": "unknown"}
            shot.motion = {"type": "unknown"}
            shot.typography = {"has_text": False}
            shot.visual_effects = []
            shot.ae_hypothesis = {}

        # 4. Recipe 生成
        _project_state.analysis_status = "generating_recipe"
        for shot in _project_state.shots:
            recipe = generate_ae_recipe(shot.model_dump())
            recipe["difficulty"] = estimate_difficulty(recipe)
            shot.ae_recipe = recipe

        _project_state.analysis_status = "done"
        _project_state.analysis_message = ""

        return {
            "status": "ok",
            "shots": [s.model_dump() for s in _project_state.shots],
        }

    except Exception as exc:
        _project_state.analysis_status = "error"
        _project_state.analysis_message = f"分析失败: {exc}"
        raise HTTPException(status_code=500, detail=_project_state.analysis_message) from exc


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
        "message": _project_state.analysis_message,
        "video": _project_state.video.model_dump() if _project_state.video else None,
        "video_path": _project_state.video_path,
        "shot_count": len(_project_state.shots),
    }


@router.get("/shots")
def list_shots():
    return {"shots": [s.model_dump() for s in _project_state.shots]}


@router.get("/shots/{shot_id}")
def get_shot(shot_id: str):
    for shot in _project_state.shots:
        if shot.shot_id == shot_id:
            return shot.model_dump()
    raise HTTPException(status_code=404, detail="Shot not found")


@router.get("/shots/{shot_id}/frame/{frame_name}")
def get_shot_frame(shot_id: str, frame_name: str):
    if _project_state.video is None:
        raise HTTPException(status_code=400, detail="未导入视频")

    project_dir = _ensure_project_dirs(_project_state.project_name)
    frame_path = project_dir / "shots" / shot_id / frame_name
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="帧文件不存在")

    return FileResponse(frame_path, media_type="image/jpeg")


@router.post("/shots/{shot_id}/analyze")
def analyze_shot(shot_id: str):
    raise HTTPException(status_code=501, detail="未实现")


@router.post("/export/json")
def export_json():
    project_dir = _ensure_project_dirs(_project_state.project_name)
    output_path = project_dir / "project.json"
    data = _project_state.model_dump()
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(output_path), "data": data}


@router.post("/export/markdown")
def export_markdown():
    project_dir = _ensure_project_dirs(_project_state.project_name)
    output_path = project_dir / "report.md"

    lines = [f"# {_project_state.project_name}", ""]
    if _project_state.video:
        v = _project_state.video
        lines.append(f"**视频**: {v.filename}")
        lines.append(f"**时长**: {v.duration}s")
        lines.append(f"**分辨率**: {v.width}x{v.height}")
        lines.append(f"**帧率**: {v.fps} fps")
        lines.append(f"**编码**: {v.codec}")
        lines.append("")

    lines.append(f"## Shots ({len(_project_state.shots)})")
    lines.append("")
    for shot in _project_state.shots:
        lines.append(f"### {shot.shot_id}")
        lines.append(f"- 时间: {shot.time.start}s - {shot.time.end}s (持续 {shot.time.duration}s)")
        lines.append(f"- 运动: {shot.motion.get('type', 'unknown')}")
        lines.append(f"- 主体: {shot.observations.get('subject_type', 'unknown')}")
        lines.append(f"- 文字: {'有' if shot.typography.get('has_text') else '无'}")
        lines.append("")

        recipe = shot.ae_recipe
        if recipe:
            lines.append("#### AE Recipe")
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
