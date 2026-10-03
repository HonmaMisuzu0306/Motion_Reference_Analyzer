# JSON Schema

## Shot Schema

```json
{
  "shot_id": "shot_032",
  "time": {
    "start": 12.43,
    "end": 14.02,
    "duration": 1.59
  },
  "frames": ["shot_032_01.jpg", "shot_032_02.jpg", "shot_032_03.jpg"],
  "observations": {},
  "motion": {},
  "typography": {},
  "visual_effects": [],
  "ae_hypothesis": {},
  "ae_recipe": {}
}
```

## Project Schema

```json
{
  "project_name": "untitled",
  "video": {
    "filename": "ref.mp4",
    "duration": 92.31,
    "width": 1920,
    "height": 1080,
    "fps": 23.976,
    "codec": "h264",
    "bitrate": 0,
    "has_audio": true
  },
  "shots": [],
  "analysis_status": "idle"
}
```

## Analysis Status

- `idle`
- `imported`
- `processing`
- `scene_detect`
- `extract_frames`
- `vision_analysis`
- `generating_recipe`
- `done`
- `error`

## M6 音频与节奏（向后兼容扩展）

Project 增加 `audio` 与 `rhythm_summary`，Shot 增加 `rhythm`，Recipe 增加 `timing`。
`audio.status` 为 `pending/ok/no_audio/silent/insufficient/error`；`tempo_bpm` 可为 null；
`beat_times` 与 `onset_times` 分开保存相对视频首帧的秒时间。`waveform` 是最多800点的RMS展示包络。
`video_origin` 是源视频首帧的原始时间戳，`audio_start` 是音轨开始在视频相对时钟上的时间。
`beat_regularity` 仅为相邻拍间隔规律性启发式值，不是准确率或概率。

```json
{
  "rhythm": {
    "status": "ok",
    "cut_time": 4.25,
    "nearest_beat": 4.017052,
    "delta_ms": 232.948,
    "beat_sync": false,
    "nearest_onset": 4.005442,
    "onset_delta_ms": 244.558,
    "tolerance_ms": 80,
    "message": ""
  }
}
```

`delta_ms = (cut_time - nearest_beat) * 1000`，正值为切镜较晚；同步为绝对差≤容差。
首镜头状态 `not_cut`，不可判断时 `nearest_beat/delta_ms/beat_sync` 为 null。
历史镜头没有 `provider_versions.video_clock.version=video-relative-v1` 且音频检测到源视频原点非零时，
状态设为 `unavailable` 并提示重新分析；`rhythm_summary.excluded_shot_count` 显式统计排除的记录。
SQLite schema4将结果保存在 projects.audio_json/rhythm_summary_json、shots.rhythm_json；不新增图片BLOB或ORM。

## V1.0 项目与运行状态

SQLite 当前 schema **5**，新增 `projects.display_name` 与 `last_opened_at`；稳定内部 `name`、ID、视频 SHA256、标签和原分析字段保留。项目 JSON 增加 `display_name`，载入后的 `library_project_id` 标识原项目。`assets_dir` 和库帧路径可使用 `@data/` 前缀，相对于外部可写数据根解析。

基础分析将 `shot.provider_versions.vision/ocr/typography` 的 provider 标为 `disabled`，同时保留 progress 的 `skipped` 阶段。UI 与报告据此区分“未执行”与“未发现”。JSON 键和已有枚举不汉化；中文仅用于显示标签及新模型自然语言提示。历史分析文本原样保留。

会话单独写入 `session.json`（项目 ID、选中 shot/library ID）；设置单独写入 `settings.json`（回环 Ollama URL、模型 ID、按语言配置的外部 OCR 目录）。损坏的设置文件明确报错，不自动覆盖。健康信息包含 `product=mra`、`version=1.0.0`、`protocol=1`、`instance_id`、`port`、`pid`。
# 局部分析扩展（schema1 / SQLite schema6）

整片JSON格式保持原样。局部记录包含 `id, project_id, kind, source_hash, request, status, progress, result, versions, warnings, error, assets_dir, created_at, updated_at`，独立保存在 `selection_analyses`，不会更新shots或标签。

`kind=frame` 请求需先从 `GET /api/v1/projects/{id}/frame-position` 获取 `frame` 身份和 `preview_token`。身份含 `stream_index, pts, time_base_num, time_base_den, video_origin, requested_time, actual_time, source_hash`。`result.frame`含静态observations/typography/visual_effects/ae_hypothesis/text_regions/ae_recipe和image；不含运动、转场、音频或文字轨迹。

`kind=clip` 请求包含有限的 `start,end`，满足 `0<=start<end<=duration` 且不超过60秒。`result`包含 `time,shots,audio,rhythm_summary`；shots增加 `frame_identities` 保存实际源PTS，图像路径相对该记录资产根。音频duration为选区长度，事件/波形时间为源视频相对坐标，出点排除；首镜头rhythm为not_cut。短于8秒没有BPM或beat_times。

`POST /api/v1/projects/{id}/selection-analyses`返回202及record_id；列表/详情通过GET获取。状态preparing/running/done/error/interrupted，重启只恢复状态、不自动重算。图片通过受限资产接口读取，导出接口支持json/markdown。模型错误以警告和局部错误保存；源内容在执行期间改变则整条记录失败，结果不发布。
