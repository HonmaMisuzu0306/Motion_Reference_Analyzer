# Motion Reference Analyzer 开发指南

> 面向静止画 MAD / Galgame OP / PV 创作者的镜头参考分析与 AE 拆解工具  
> 目标：将参考视频自动拆解为 **镜头时间轴、画面结构、运动信息、文字信息、效果推测与 AE 制作建议**，并为后续与 **LocalFX** 联动预留结构化接口。

---

## 1. 项目定位

### 1.1 项目目标

Motion Reference Analyzer（以下简称 MRA）不是“自动复刻 PV”的工具，也不是视频剪辑器。

它的核心目标是：

```text
参考视频
  ↓
镜头切分
  ↓
代表帧提取
  ↓
运动分析
  ↓
视觉理解
  ↓
文字 / 构图 / 效果判断
  ↓
AE 制作建议
  ↓
结构化 JSON / Markdown
```

最终帮助创作者回答：

- 这个镜头是怎么运动的？
- 人物、背景、文字可能如何分层？
- 这个镜头在 AE 里大概怎么搭？
- 是否需要 3D / Blender？
- 是否适合用静止画 MAD 的方式实现？
- 哪些效果可以交给 LocalFX 进一步生成？

---

## 2. 目标用户

主要用户：

- 静止画 MAD 制作者
- Galgame OP / PV 学习者
- After Effects 用户
- Motion Graphics 学习者
- 需要拆解参考镜头的创作者

优先支持的场景：

- 静止画 MAD
- Galgame OP
- 日系 PV
- Typography
- 2.5D Parallax
- Camera Push / Pan / Shake
- Mask / Shape / Glow / Blur
- 人物分层
- 节奏型转场

---

## 3. 非目标

第一阶段不要做：

- 自动完整复刻 PV
- Blender 场景重建
- 自动生成完整 AE 工程
- 多 Agent 系统
- 复杂 3D 相机求解
- 全视频逐帧语义分析
- 云端 SaaS
- 用户系统
- 在线支付
- 插件市场
- 大规模模型训练

原则：

> 先做“能稳定拆镜头并给出可信 AE 制作建议”的本地工具。

---

# 4. 推荐技术栈

## 4.1 桌面端

推荐：

- **Tauri 2**
- **React**
- **TypeScript**
- Vite
- Zustand（状态管理，可选）
- Tailwind CSS 或普通 CSS Modules

原因：

- UI 易开发
- 时间轴、卡片、播放器布局方便
- 后续可打包为 Windows 桌面应用
- 可以调用本地 Python sidecar

---

## 4.2 分析核心

推荐：

- **Python 3.11+**
- PyAV
- FFmpeg / ffprobe
- PySceneDetect
- OpenCV
- NumPy
- Pydantic

可选：

- PaddleOCR
- ONNX Runtime
- llama.cpp / Ollama / vLLM / transformers

---

## 4.3 本地视觉模型

第一阶段采用统一 Provider 接口，不把代码写死到具体模型。

推荐优先测试：

- Qwen3-VL 2B
- Qwen3-VL 4B
- Qwen3-VL 8B

根据设备能力切换。

接口建议：

```python
class VisionProvider:
    def analyze_images(self, images, prompt):
        ...

    def get_model_info(self):
        ...
```

未来可扩展：

- Ollama
- llama.cpp
- OpenAI-compatible local endpoint
- LM Studio
- vLLM
- 其他本地 VLM

---

# 5. 总体架构

```text
┌──────────────────────────────────────┐
│              Tauri App               │
│                                      │
│  React UI                            │
│  - Video Player                      │
│  - Shot List                         │
│  - Timeline                          │
│  - Analysis Panel                    │
│  - AE Recipe Panel                   │
└──────────────────┬───────────────────┘
                   │
                   │ Local API / IPC
                   ▼
┌──────────────────────────────────────┐
│        Python Analysis Core          │
├──────────────────────────────────────┤
│ Video Core                           │
│  - Metadata                          │
│  - Decode                            │
│  - Shot Detection                    │
│                                      │
│ CV Core                              │
│  - Optical Flow                      │
│  - Camera Motion                     │
│                                      │
│ OCR Core                             │
│  - Text Detection                    │
│  - Text Recognition                  │
│                                      │
│ AI Core                              │
│  - Vision Provider                   │
│  - Shot Analyzer                     │
│                                      │
│ Recipe Core                          │
│  - AE Recipe Generator               │
└──────────────────┬───────────────────┘
                   │
                   ▼
        Structured Shot JSON
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
   Markdown Report       Future LocalFX
```

---

# 6. 推荐目录结构

```text
motion-reference-analyzer/
│
├─ apps/
│  └─ desktop/
│     ├─ src/
│     │  ├─ components/
│     │  ├─ pages/
│     │  ├─ stores/
│     │  ├─ services/
│     │  └─ types/
│     ├─ src-tauri/
│     └─ package.json
│
├─ core/
│  ├─ app/
│  │  ├─ main.py
│  │  └─ api.py
│  │
│  ├─ video/
│  │  ├─ metadata.py
│  │  ├─ decoder.py
│  │  ├─ scene_detect.py
│  │  └─ frame_sampler.py
│  │
│  ├─ vision/
│  │  ├─ provider.py
│  │  ├─ qwen_provider.py
│  │  └─ prompts.py
│  │
│  ├─ cv/
│  │  ├─ optical_flow.py
│  │  ├─ camera_motion.py
│  │  └─ motion_classifier.py
│  │
│  ├─ ocr/
│  │  ├─ paddle_provider.py
│  │  └─ typography.py
│  │
│  ├─ recipe/
│  │  ├─ ae_recipe.py
│  │  └─ difficulty.py
│  │
│  ├─ schemas/
│  │  ├─ shot.py
│  │  ├─ motion.py
│  │  ├─ typography.py
│  │  └─ recipe.py
│  │
│  └─ tests/
│
├─ docs/
│  ├─ ARCHITECTURE.md
│  ├─ JSON_SCHEMA.md
│  ├─ MODEL_PROVIDER.md
│  └─ ROADMAP.md
│
├─ samples/
│
├─ output/
│
├─ scripts/
│
├─ pyproject.toml
└─ README.md
```

---

# 7. MVP 范围

第一版 MVP 只完成以下能力：

1. 导入 MP4 / MOV
2. 获取视频元数据
3. 自动分镜
4. 每个镜头提取 3 张代表帧
5. 将代表帧组成 Contact Sheet
6. 使用本地 VLM 分析镜头
7. 输出结构化 Shot JSON
8. 生成 AE Recipe
9. 在 UI 中浏览 Shot
10. 导出 JSON
11. 导出 Markdown 报告

暂不实现：

- Beat Sync
- Reference Library
- 相似镜头搜索
- LocalFX 实际调用
- 自动创建 AE 工程

---

# 8. 开发阶段

---

## Phase 0 — 项目初始化

### 目标

建立可运行的桌面端 + Python Core。

### 工作内容

- 创建 Tauri + React 项目
- 创建 Python Core
- 建立 IPC / Local API
- 完成视频文件选择
- Python 能收到视频路径

### 验收标准

点击：

```text
Import Video
```

选择 MP4 后，UI 能显示：

```text
filename
duration
resolution
fps
codec
```

---

# 9. Phase 1 — 视频解析与镜头切分

## 9.1 视频元数据

使用：

```text
ffprobe
```

读取：

- duration
- width
- height
- fps
- codec
- bitrate
- audio track

输出：

```json
{
  "duration": 92.31,
  "width": 1920,
  "height": 1080,
  "fps": 23.976
}
```

---

## 9.2 Scene Detection

使用：

```text
PySceneDetect
```

优先：

```text
AdaptiveDetector
```

每个镜头输出：

```json
{
  "shot_id": "shot_001",
  "start": 0.0,
  "end": 1.34,
  "duration": 1.34
}
```

---

## 9.3 代表帧策略

不要每个镜头只截中间帧。

默认采样：

```text
15%
50%
85%
```

例如：

```text
Shot: 10.0s - 12.0s
```

取：

```text
10.3s
11.0s
11.7s
```

对于超过 5 秒的 Shot：

建议增加到 5 帧。

---

## 9.4 Contact Sheet

每个 Shot 生成：

```text
┌────────┬────────┬────────┐
│ Frame1 │ Frame2 │ Frame3 │
└────────┴────────┴────────┘
```

保存：

```text
output/{project}/shots/shot_001/contact.jpg
```

---

# 10. Phase 2 — VLM 镜头分析

## 10.1 VLM 输入

输入：

- Contact Sheet
- Shot Metadata
- 固定 Prompt

模型不要自由发挥。

必须要求：

```text
ONLY RETURN JSON
```

---

## 10.2 分析维度

VLM 分析：

### Composition

- 主体类型
- 主体位置
- 背景类型
- 是否明显分层
- 画面空间关系

### Motion

- static
- push_in
- pull_out
- pan_left
- pan_right
- tilt_up
- tilt_down
- shake
- rotation
- complex

### Typography

- 是否有文字
- 文字区域
- 文字用途
- 是否有明显动态

### Visual Effects

只输出“视觉上疑似存在”。

例如：

- glow
- blur
- chromatic aberration
- noise
- bloom
- vignette
- grain
- particles

不要断言作者实际使用了某个 AE Effect。

---

# 11. 数据结构设计

## 11.1 Shot Schema

建议：

```json
{
  "shot_id": "shot_032",

  "time": {
    "start": 12.43,
    "end": 14.02,
    "duration": 1.59
  },

  "frames": [
    "shot_032_01.jpg",
    "shot_032_02.jpg",
    "shot_032_03.jpg"
  ],

  "observations": {},

  "motion": {},

  "typography": {},

  "visual_effects": [],

  "ae_hypothesis": {},

  "ae_recipe": {}
}
```

---

# 12. 观察与推测必须分离

这是核心设计原则。

禁止：

```json
{
  "effect": "AE Glow"
}
```

推荐：

```json
{
  "observations": {
    "bright_edge_bloom": true
  },

  "ae_hypothesis": {
    "possible_effects": [
      {
        "name": "Glow",
        "confidence": 0.72
      }
    ]
  }
}
```

原因：

成片无法证明作者真实工程使用了什么。

系统只能：

- 观察视觉现象
- 给出 AE 实现方案

---

# 13. Phase 3 — AE Recipe Generator

AE Recipe 是项目最重要的输出。

示例：

```json
{
  "layers": [
    {
      "role": "background",
      "suggestion": "separate background layer"
    },
    {
      "role": "character",
      "suggestion": "isolated character layer"
    }
  ],

  "camera": {
    "type": "push_in",
    "strength": 0.25
  },

  "transform": {
    "character_scale": {
      "from": 102,
      "to": 110
    }
  },

  "typography": {
    "method": "mask_reveal",
    "duration": 0.35
  },

  "effects": [
    "Glow",
    "Gaussian Blur"
  ]
}
```

---

# 14. AE Recipe 文本展示

UI 中同时显示创作者可读版本：

```text
Shot #032
12.43s — 14.02s

【画面拆分】

背景
人物
前景粒子
Typography

【运动】

整体：
轻微 Push In

人物：
Scale 102% → 110%

背景：
Scale 100% → 104%

【文字】

建议：
Mask Reveal

时长：
约 0.35s

【视觉效果】

可能可使用：
Glow
Gaussian Blur

【制作难度】

AE：
★★☆☆☆

Blender：
不需要

素材分层：
需要

静止画 MAD 适配：
高
```

---

# 15. Phase 4 — 传统 CV 运动分析

MVP 完成后再加入。

推荐：

- Feature Detection
- Lucas-Kanade Optical Flow
- Farneback Optical Flow
- Affine Transform Estimation
- Homography

目标：

得到更客观的数据：

```json
{
  "translation_x": 32.4,
  "translation_y": -5.2,
  "scale_ratio": 1.073,
  "rotation_deg": -0.4
}
```

然后转换为：

```text
Camera Push
轻微右移
低强度旋转
```

---

# 16. Phase 5 — OCR 与 Typography

推荐：

```text
PaddleOCR
```

输出：

```json
{
  "text": "その後、虚無は消え失せ",
  "bbox": [182, 731, 604, 812],
  "confidence": 0.94
}
```

再交由 VLM 判断：

- Title
- Lyrics
- Character Name
- Decorative Typography
- Narrative Text

---

# 17. Phase 6 — Reference Library

数据库：

```text
SQLite
```

结构：

```text
Project

Video

Shot

Frame

Analysis

Motion

Typography

AERecipe

Tag
```

支持搜索：

```text
camera push

mask typography

character entrance

parallax

glow

duration < 2s

MAD suitable
```

---

# 18. Phase 7 — 音频节奏分析

后续加入：

- librosa
- aubio
- essentia

分析：

- beat
- onset
- transient
- shot cut timing

输出：

```json
{
  "cut_time": 13.421,
  "nearest_beat": 13.397,
  "delta_ms": 24,
  "beat_sync": true
}
```

---

# 19. UI 设计

第一版推荐布局：

```text
┌────────────────────────────────────────────┐
│ Motion Reference Analyzer                 │
├───────────────┬────────────────────────────┤
│               │                            │
│  Shot List    │         Video              │
│               │                            │
│  #001         ├────────────────────────────┤
│  #002         │ Timeline                   │
│  #003         │ ┃━━━━┃━━┃━━━━━━┃━━┃       │
│               │                            │
│               ├────────────────────────────┤
│               │ Shot Analysis              │
│               │                            │
│               │ Motion: Push In            │
│               │ Typography: Left           │
│               │ Effects: Glow / Blur       │
│               │                            │
│               │ [ AE Recipe ]              │
└───────────────┴────────────────────────────┘
```

原则：

- 不模仿 Premiere
- 不做复杂 NLE
- 重点是 Reference Browser

---

# 20. 状态管理

建议前端状态：

```ts
interface ProjectState {
  video: VideoInfo | null;
  shots: Shot[];
  selectedShotId: string | null;
  analysisStatus: AnalysisStatus;
}
```

AnalysisStatus：

```text
idle
processing
scene_detect
extract_frames
vision_analysis
generating_recipe
done
error
```

---

# 21. Python Core API

建议最初提供：

```text
POST /video/import
POST /video/analyze
GET  /project/status
GET  /shots
GET  /shots/{id}
POST /shots/{id}/analyze
POST /export/json
POST /export/markdown
```

未来如果改 Tauri IPC，也保持业务层接口结构。

---

# 22. 输出目录

推荐：

```text
output/
└─ project_name/
   ├─ project.json
   ├─ report.md
   ├─ thumbnails/
   ├─ shots/
   │  ├─ shot_001/
   │  │  ├─ frame_01.jpg
   │  │  ├─ frame_02.jpg
   │  │  ├─ frame_03.jpg
   │  │  └─ contact.jpg
   │  └─ shot_002/
   └─ analysis/
      ├─ shot_001.json
      └─ shot_002.json
```

---

# 23. 模型 Prompt 原则

视觉模型 Prompt 必须：

- 要求结构化 JSON
- 不允许输出 Markdown
- 不允许编造插件名称
- 将 Observation 与 AE Hypothesis 分离
- 必须输出 Confidence
- 不确定时允许 unknown

错误示例：

```text
这个镜头一定使用了 Trapcode Particular。
```

正确：

```json
{
  "observation": "foreground particle-like elements",
  "ae_hypothesis": {
    "method": "particle system",
    "confidence": 0.58
  }
}
```

---

# 24. 缓存机制

AI 分析较慢，因此必须缓存。

Hash：

```text
video hash
+
shot timestamp
+
model id
+
prompt version
```

如果未变化：

```text
reuse previous result
```

不要重复跑模型。

---

# 25. 错误恢复

任何分析步骤都不能让整个项目报废。

例如：

```text
Shot 001 ✅
Shot 002 ✅
Shot 003 ❌
Shot 004 ✅
```

Shot 003 可以单独：

```text
Retry
```

而不是重新分析整个视频。

---

# 26. 日志

必须记录：

```text
logs/app.log
```

包括：

- ffmpeg command
- scene detect time
- model loading
- inference time
- errors
- JSON parse failure
- retry

禁止记录：

- 用户隐私信息
- 密钥
- Token

---

# 27. 性能策略

优先：

```text
Proxy Video
```

分析时不一定使用原始 4K 视频。

推荐：

```text
720p / 1080p Proxy
```

Shot Detection：

```text
低分辨率
```

最终截图：

```text
需要时用原图
```

---

# 28. LocalFX 接口预留

MRA 不直接控制 AE。

未来：

```text
Motion Reference Analyzer
        ↓
AE Recipe JSON
        ↓
LocalFX
        ↓
Local AI
        ↓
Effect / Animation Graph
        ↓
After Effects
```

建议预留：

```json
{
  "localfx": {
    "compatible": true,
    "schema_version": "0.1"
  }
}
```

未来按钮：

```text
Send to LocalFX
```

---

# 29. 与 LocalFX 的职责边界

## Motion Reference Analyzer

负责：

```text
看懂参考
```

包括：

- 镜头分析
- 运动分析
- 文字分析
- AE 制作建议

## LocalFX

负责：

```text
生成效果
```

包括：

- 自然语言理解
- 本地模型推理
- Effect Graph
- AE 参数生成
- AE 实际执行

不要把两个项目过早耦合。

---

# 30. Roadmap

## V0.1

- Tauri UI
- 视频导入
- ffprobe
- PySceneDetect
- Shot List
- 代表帧
- Timeline

## V0.2

- Local VLM
- Contact Sheet
- Shot JSON
- AE Recipe
- Markdown Export

## V0.3

- Optical Flow
- Camera Motion
- Motion Confidence

## V0.4

- PaddleOCR
- Typography Analysis

## V0.5

- SQLite
- Reference Library
- Search / Tags

## V0.6

- Beat Detection
- Rhythm Analysis

## V1.0

- 完整本地桌面版
- Installer
- Model Management
- Project Management

## V1.5

- LocalFX Integration
- Send to LocalFX
- Shared AE Recipe Schema

---

# 31. MVP 验收标准

第一版完成时：

给项目一个 MP4。

系统必须能够：

1. 成功读取视频
2. 自动划分 Shot
3. 左侧展示 Shot List
4. 点击 Shot 可预览
5. 显示三张代表帧
6. 本地模型完成镜头分析
7. 输出合法 JSON
8. 显示 AE Recipe
9. 导出 Markdown
10. 导出 JSON

示例输出：

```text
Shot #014

Duration:
1.47s

Motion:
Push In

Subject:
Character

Typography:
Present

Visual:
Glow-like bloom

AE Recipe:
Character Scale 103 → 110
Background Scale 100 → 104
Text Mask Reveal ~0.4s
```

完成以上内容即可视为：

```text
MVP DONE
```

---

# 32. 第一版暂缓功能

以下需求发现后先写入 TODO：

```text
TODO-LATER
```

不要即时实现：

- Blender integration
- AE MCP
- LocalFX direct call
- auto reconstruction
- multi-agent
- vector database
- cloud sync
- online model API
- collaboration
- full semantic search
- automatic plugin detection

---

# 33. 开发原则

### 原则一

先做可靠的数据流水线。

### 原则二

传统算法解决能量化的问题。

### 原则三

VLM 解决语义问题。

### 原则四

不让 AI 把“推测”写成“事实”。

### 原则五

所有 AI 输出必须结构化。

### 原则六

所有分析步骤必须可重试。

### 原则七

所有昂贵步骤必须缓存。

### 原则八

MVP 不与 LocalFX 强耦合。

### 原则九

静止画 MAD 工作流优先。

### 原则十

Reference Browser，而不是 Video Editor。

---

# 34. WorkBuddy / Codex 开发顺序

推荐 Agent 严格按以下顺序工作：

```text
TASK-001
初始化 Tauri + React

TASK-002
初始化 Python Core

TASK-003
实现 ffprobe metadata

TASK-004
实现视频导入

TASK-005
实现 Scene Detection

TASK-006
实现代表帧提取

TASK-007
实现 Shot List

TASK-008
实现 Timeline

TASK-009
定义 Pydantic Shot Schema

TASK-010
实现 VisionProvider

TASK-011
接入第一个本地 VLM

TASK-012
实现 Shot Analyzer

TASK-013
实现 AE Recipe Generator

TASK-014
实现 Markdown Export

TASK-015
实现 JSON Export

TASK-016
完成 MVP Debug
```

每个 Task 完成以后：

```text
运行
测试
修复
提交
```

再开始下一个。

---

# 35. 最终愿景

长期架构：

```text
参考 MAD / OP / PV
        ↓
Motion Reference Analyzer
        ↓
Shot Understanding
        ↓
AE Recipe
        ↓
LocalFX
        ↓
Local AI
        ↓
Effect / Animation Graph
        ↓
After Effects
```

最终目标不是让 AI 替创作者“自动做完整作品”。

而是：

> 让创作者看到优秀参考时，可以快速知道它为什么有效、在 AE 中如何实现，并把重复性的技术搭建工作交给本地 AI 辅助完成。

---

## End
