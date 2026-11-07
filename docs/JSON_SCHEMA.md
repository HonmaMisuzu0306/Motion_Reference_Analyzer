# JSON Schema

## 开发版：轨迹、分镜与 AE 试作（未发布）

本节描述当前源码的新分析记录，不表示 V1.0.0 安装器已包含这些字段。

| 层级 | 当前标识 | 定义位置 |
| --- | --- | --- |
| 整片流水线 | `mra-pipeline-v4-trajectories` | `core/app/api.py` |
| 片段流水线 | `selection-pipeline-v4-trajectories` | `core/selection/pipeline.py` |
| 分镜 | `spatial-affine-v4` | `core/video/scene_features.py` |
| CV 缓存/质量判据 | `v5-short-shot-tracking-retry` | `core/cv/cache.py` |
| 音频缓存身份校验 | `audio-source-verified-v1` | `core/audio/cache.py` |
| 整片 OCR 待发布缓存 | `v4-actual-pts-verified-source` | `core/ocr/pending_cache.py` |
| 动态 Recipe | `ae-recipe-v5-artwork-padding` | `core/recipe/keyframes.py` |
| JSX 内嵌试作数据 | `ae-setup-v1` | `core/recipe/ae_script.py` |

CV 缓存算法标识以 `core/cv/cache.py` 的 `CV_ALGORITHM_VERSION` 为准；质量判据或轨迹语义改变时应更新它，
不允许新算法复用旧判据结果。分镜和 Recipe 版本写入 shot/provider 或局部记录的 versions；
旧记录保留原版本，不原地伪装成新分析。SQLite 仍为 schema6，本轮字段沿用已有 JSON 存储，无需新增表迁移。

### `measured_motion`：坐标与分段

`frame_width/frame_height` 为源画面尺寸；`translation_reference` 为 `frame_center` 或历史默认值
`legacy_top_left`。新轨迹以画面中心为平移参考，x 正向为右，y 正向为下，正旋转为顺时针。
`trajectory_status` 为 `not_measured/complete/partial`；`complete` 表示采样帧对连续，不表示覆盖镜头每一帧或测量必然准确。

`trajectory` 中每个点具有下列字段：

| 字段 | 含义 |
| --- | --- |
| `source_time` | 实际解码 PTS 转换的源视频相对秒，不是采样序号或名义 FPS 推算时间 |
| `segment_id` / `segment_start_time` | 连续跟踪段编号、该段参考帧的源视频时间 |
| `matrix` | 原始像素坐标的 2×3 矩阵；将本段参考帧坐标映射到当前采样帧 |
| `translation_x_px/translation_y_px` | 该矩阵作用于画面中心后得到的中心位移（像素） |
| `translation_x_ratio/translation_y_ratio` | 中心位移除以源画面宽/高，`0.1` 表示 10% |
| `scale_ratio` | 相对本段起点的比例，`1` 为 100% |
| `rotation_deg` | 相对本段起点累计的角度，保留超过 180° 的连续累计值 |

矩阵按时间顺序复合；旋转和缩放会影响后续位移，不能简单把帧对的 `dx/dy` 相加。
无效帧对结束当前跟踪段，下一段重新以单位矩阵、零位移、100% 缩放、0° 旋转开始。
不同段不能拼接成完整镜头运动。帧对 `pairs` 也保存 `start_time/end_time/valid`，可追溯缺口。

`status` 为 `ok/insufficient_features/too_few_valid_pairs/high_variance/incomplete_tracking/failed`。
缺口通常返回 `incomplete_tracking`；证据更少时可返回特征不足或有效帧对不足。此时顶层累计值不能当作可靠静止结果。
旧记录缺少轨迹时，界面保留历史累计值并提示重新分析，不合成虚构曲线。
`confidence/stability/shake_score` 为工程质量描述；其中平滑性与跟踪可靠性不能等同，也不解释成自然视频正确率。
当前 `method=goodFeaturesToTrack_LK_affine_time_aware_center_v4`；平滑性基于真实时间间隔的局部速度变化，
抖动需有超过噪声阈值、具有幅度与频率依据的反复转向。一次往返或快速单向平移不自动等同于抖动，
分段缺口不构成转向；这些描述不判断创作意图。
当前测量入口流式处理相邻采样帧，保留轻量帧对/轨迹结果，不将全片采样图像常驻内存；
兼容函数 `sample_frames_for_cv` 仍会返回图像列表，仅供明确需要完整列表的调用方使用。
采样节奏比较包含 1ns 数值容差，避免浮点网格误差跳过计划采样帧；镜头入/出边界仍严格采用 `[start,end)`，
该容差不允许把范围外的帧纳入轨迹。

### `animation_plan`：时间、曲线与兼容端点

`evidence_source` 为 `measured/semantic/insufficient`。采用测量至少需要 `status=ok`、
`confidence≥0.5`、两个有效帧对及有限数值；新轨迹还必须满足完整单段、画面中心参考、正尺寸、
递增时间、样本/帧对计数和矩阵/摘要一致性校验。可靠静止测量不会被 AI 推近判断覆盖。
测量不足时，合格的语义方向可提供明确标注的手动试作值，但不允许据此导出实测运动 JSX。

| 字段 | 时间/数据语义 |
| --- | --- |
| `source_start/source_end` | 镜头在源视频中的半开范围 `[start,end)`，单位秒 |
| `duration` | 镜头时长 |
| `coverage_start/coverage_end` | 首个/末个实际轨迹点的**源视频秒**；没有合格轨迹时为 null |
| `time_origin` | 人类可读的时间基准说明 |
| `curves[].points[].time` | **镜头局部秒**，即 `source_time - source_start` |
| `curves[].points[].value` | 该属性的实际关键帧值，单位由 `unit` 指定 |
| `keyframes` | 兼容旧消费者的首尾摘要；`start_time/end_time` 同样为局部秒 |
| `notes` | 证据、坐标前提、采样和试作限制 |

新轨迹的曲线只保留实际采样时间，末点须小于镜头出点；不将首尾外推到镜头边界。
范围不合法或轨迹越界时，不生成带时间曲线/端点。旧记录没有轨迹时，可保留局部 0 秒到时长的端点试作安排，
但它没有真实采样覆盖依据，不能排除中途往返。单帧与仅含一个实际帧的极短选区仍使用静态 Recipe。

`curves` 按属性独立简化，`interpolation=linear`；`sample_count` 是输入采样数，
`keyframe_count` 是保留点数。当前各属性最小变化范围均为 0.5 个相应单位：

| `property` | `unit` | 简化容差 `tolerance` |
| --- | --- | --- |
| `position_x` | 画面宽度（%） | 0.1 百分点 |
| `position_y` | 画面高度（%） | 0.1 百分点 |
| `global_scale` | 缩放（%），100 为原大小 | 0.2 百分点 |
| `rotation` | 角度（°） | 0.1° |

容差限制的是被省略**采样点**的线性重建误差，不是跟踪误差，也不约束两个实际采样时刻之间的未知运动。
首尾相同仍可能有显著往返，消费者应优先读取 `curves`，不能只根据 `transform.from/to` 判断静止。
`transform` 保留 `from/to/unit/basis`，完整轨迹还提供 `min_value/max_value`。
AI 平移回退可使用像素试作单位，不能与测量的宽/高百分比混用。

以下为一段水平往返的字段摘录；镜头 12–14 秒，实际测量只到 13.875 秒：

```json
{
  "time": {"start": 12, "end": 14, "duration": 2},
  "measured_motion": {
    "status": "ok", "confidence": 0.9,
    "frame_width": 1000, "frame_height": 500,
    "translation_reference": "frame_center", "trajectory_status": "complete",
    "sample_count": 3, "valid_pair_count": 2, "total_pair_count": 2,
    "translation_x_ratio": 0, "translation_y_ratio": 0, "scale_ratio": 1,
    "scale_change_percent": 0, "rotation_deg": 0,
    "trajectory": [
      {"source_time": 12.125, "segment_id": 0, "segment_start_time": 12.125, "translation_x_px": 0, "translation_x_ratio": 0, "scale_ratio": 1, "rotation_deg": 0, "matrix": [[1,0,0],[0,1,0]]},
      {"source_time": 12.375, "segment_id": 0, "segment_start_time": 12.125, "translation_x_px": 100, "translation_x_ratio": 0.1, "scale_ratio": 1, "rotation_deg": 0, "matrix": [[1,0,100],[0,1,0]]},
      {"source_time": 13.875, "segment_id": 0, "segment_start_time": 12.125, "translation_x_px": 0, "translation_x_ratio": 0, "scale_ratio": 1, "rotation_deg": 0, "matrix": [[1,0,0],[0,1,0]]}
    ]
  },
  "ae_recipe": {
    "version": "ae-recipe-v5-artwork-padding",
    "animation_plan": {
      "evidence_source": "measured",
      "source_start": 12, "source_end": 14, "duration": 2,
      "coverage_start": 12.125, "coverage_end": 13.875,
      "time_origin": "镜头局部秒；0 秒对应源视频 source_start",
      "curves": [{
        "property": "position_x", "unit": "画面宽度（%）", "basis": "连续全局运动测量",
        "interpolation": "linear", "tolerance": 0.1, "sample_count": 3, "keyframe_count": 3,
        "points": [{"time": 0.125, "value": 0}, {"time": 0.375, "value": 10}, {"time": 1.875, "value": 0}]
      }],
      "keyframes": [{"property": "position_x", "unit": "画面宽度（%）", "basis": "连续全局运动测量", "start_time": 0.125, "end_time": 1.875, "from": 0, "to": 0}],
      "notes": ["仅覆盖实际采样；参数为复现起点。"]
    }
  }
}
```

JSON、参考库、局部导出保留轨迹和曲线；Markdown 展示实际关键帧时间、数值、单位与依据。
界面以曲线和折叠列表呈现，不默认展开原始 `trajectory/pairs` 数组。

### 缓存和源身份

CV 缓存键包含源文件内容 SHA256、精确的 start/end/target_fps、max_long_edge 与算法版本。
浮点时间使用精确表示区分亚毫秒边界；文件名、大小、mtime 不作为内容身份。
同内容可跨路径复用，同名、同大小、同 mtime 的不同内容不能复用。
直接调用缓存且不传 `source_hash` 时，每次重新计算内容身份；传入时，调用方必须已在本次请求验证 SHA256，
并在发布结果前再次检查。整片分析先写私有候选，最终身份复核后一次替换工作项目；复核失败保留原 shots、audio 与 assets_dir。
CV 和整片 OCR 缓存均延迟到该复核之后发布。整片 OCR 使用 `strict_range=True`，仅在镜头半开范围内采样。
损坏、非有限数值或失败结果不被当作有效命中，缓存文件采用临时文件和原子替换写入。

整片音频缓存另使用 `audio-source-verified-v1` 命名空间，隔离此前未做结束身份复核的旧条目。
`analyze_audio` 每次正常调用在开始和返回前各读取一次源内容 SHA256，缓存命中、强制分析、禁用缓存均执行身份复核；
缓存键复用本次开始时的身份，避免额外重复读取。源文件变化或无法读取时返回 `audio.status=error`，
不返回已有命中或本轮波形/节拍，也不写入缓存。已按新版规则缓存的内容恢复后仍可命中其有效条目；
旧命名空间文件保留但不读取。
这是音频模块调用的检查，不对每个镜头重复执行。API 还会为项目来源归属做额外校验，不能据此声称整条 HTTP 请求只读两次。
音频重试在私有候选中计算，项目来源与最终内容复核后才发布；音频检测算法标识仍为 `librosa-beat-onset-v2-video-clock`。

导入在读取元数据前后检查内容，源被替换时返回 409 并保留原项目。手动保存尊重已捕获的 `Project.source_hash`：
可读源与该身份不符时拒绝保存（409），源已缺失时仍保留原 hash，不把旧分析改记成新文件身份。

### 分镜与短镜头

`spatial-affine-v4` 在整片和片段分析中共用空间颜色、平移/旋转/缩放连续性及单帧闪光证据。
同均色但布局不同的画面仍可检测硬切；连续平移与闪光有专门的抑制判据。
默认最短镜头过滤为 0，保留可检测的快速剪辑和两帧插入；不保证任意单帧插入都能与闪光区分。
选区只使用其范围内可见帧，不借出点之后的画面决定边界。该检测器不提供叠化识别或自然视频准确率保证。
整片镜头边界保留实际源时间精度，不再统一 round 到三位小数；界面显示精度不改变数据精度。

### AE JSX 导出接口

以下接口均为无请求体的 `POST`，统一前缀 `/api/v1`：

| 路径 | 对象 |
| --- | --- |
| `/shots/{shot_id}/export/ae` | 当前工作项目镜头 |
| `/library/shots/{db_id}/export/ae` | 已保存的参考库镜头 ID |
| `/selection-analyses/{rid}/shots/{shot_id}/export/ae` | 已完成片段分析中的镜头；单帧记录不支持 |

成功返回 `{"path":"绝对路径.jsx","message":"使用说明"}`。文件写入应用输出根的 `ae_exports`，
文件名独立；接口不启动 AE。证据或尺寸/时间/FPS 不满足要求时返回 409 和可读原因，镜头不存在为 404，
无法写入输出目录为 503。执行前服务端从保存的测量证据重新生成 Recipe，不直接执行客户端或缓存 Recipe 中的文字。
尺寸要求 4–30000 像素，帧率 1–999 fps，时长至少一帧且不超过 10800 秒；轨迹尺寸必须与视频元数据一致。
只导出连续、可靠且具有变化的实测曲线；具体操作和真实环境验收限制见 [AE 运动流程](AE_MOTION_WORKFLOW.md)。

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

SQLite schema **5** 阶段新增 `projects.display_name` 与 `last_opened_at`；当前局部分析扩展使用下文的 schema **6**。稳定内部 `name`、ID、视频 SHA256、标签和原分析字段保留。项目 JSON 增加 `display_name`，载入后的 `library_project_id` 标识原项目。`assets_dir` 和库帧路径可使用 `@data/` 前缀，相对于外部可写数据根解析。

基础分析将 `shot.provider_versions.vision/ocr/typography` 的 provider 标为 `disabled`，同时保留 progress 的 `skipped` 阶段。UI 与报告据此区分“未执行”与“未发现”。JSON 键和已有枚举不汉化；中文仅用于显示标签及新模型自然语言提示。历史分析文本原样保留。

会话单独写入 `session.json`（项目 ID、选中 shot/library ID）；设置单独写入 `settings.json`（回环 Ollama URL、模型 ID、按语言配置的外部 OCR 目录）。损坏的设置文件明确报错，不自动覆盖。健康信息包含 `product=mra`、`version=1.0.0`、`protocol=1`、`instance_id`、`port`、`pid`。
# 局部分析扩展（schema1 / SQLite schema6）

整片JSON格式保持原样。局部记录包含 `id, project_id, kind, source_hash, request, status, progress, result, versions, warnings, error, assets_dir, created_at, updated_at`，独立保存在 `selection_analyses`，不会更新shots或标签。

`kind=frame` 请求需先从 `GET /api/v1/projects/{id}/frame-position` 获取 `frame` 身份和 `preview_token`。身份含 `stream_index, pts, time_base_num, time_base_den, video_origin, requested_time, actual_time, source_hash`。`result.frame`含静态observations/typography/visual_effects/ae_hypothesis/text_regions/ae_recipe和image；不含运动、转场、音频或文字轨迹。

`kind=clip` 请求包含有限的 `start,end`，满足 `0<=start<end<=duration` 且不超过60秒。`result`包含 `time,shots,audio,rhythm_summary`；shots增加 `frame_identities` 保存实际源PTS，图像路径相对该记录资产根。音频duration为选区长度，事件/波形时间为源视频相对坐标，出点排除；首镜头rhythm为not_cut。短于8秒没有BPM或beat_times。

`POST /api/v1/projects/{id}/selection-analyses`返回202及record_id；列表/详情通过GET获取。状态preparing/running/done/error/interrupted，重启只恢复状态、不自动重算。图片通过受限资产接口读取，导出接口支持json/markdown。模型错误以警告和局部错误保存；源内容在执行期间改变则整条记录失败，结果不发布。

动态 Recipe 的 `typography[].track_id` 关联同一镜头的 OCR 文字轨迹。时间为源视频中首次和末次识别的采样时间；单次识别只提供排版参考。旧 Recipe 没有该字段时，桌面端按文字与采样起止时间匹配。

开发版 `animation_plan.artwork_padding` 仅在完整、可信且采样均在镜头内的实测轨迹可估算时提供。
`left_px`、`right_px`、`top_px`、`bottom_px` 为从原画框向外增加的非负整数像素，`width_px` 和 `height_px` 为包含留边的总尺寸。
估算覆盖导出的分段线性变换及其间经过的角度，以整数像素向外取整。该范围不代表原片在采样之间的真实运动。总宽或总高超过 30000 像素，或无法在计算预算内求得足够紧的界限时，省略建议。

### 跨帧运动复核
实测运动的 long_baseline_check_count 记录已尝试的跨帧区间数，long_baseline_conflict_count 记录正向、反向跟踪均证实多组运动不一致的区间数。两项均为非负整数。相邻 valid_pair_count 与 total_pair_count 不包含跨帧复核；即使每个相邻帧对都有效，也可能因多个非重叠区间重复确认冲突而返回 mixed_support、没有可导出的全局轨迹。历史记录缺失这些字段时无法判断旧分析是否执行了复核。
