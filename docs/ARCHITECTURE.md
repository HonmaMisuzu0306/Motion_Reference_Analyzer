# Architecture

Motion Reference Analyzer 采用桌面端 + Python 分析核心的分层架构。

## V1.0 桌面运行结构

Windows 安装版包含 Tauri/React UI 和 PyInstaller 冻结 Python 核心。Rust 在隐藏窗口中启动自己的核心进程，绑定回环动态端口，并校验 `MRA_READY` 与 `/health` 的产品、版本、协议和实例身份。所有 API/媒体请求使用该端点；退出只回收本实例子进程树。异常退出提供重试与日志入口。浏览器开发模式可独立连接开发服务。

UI 采用深色专业工作台：镜头列表、单一视频预览、镜头详情和底部节奏轨道。统一带 sequence 的定位请求保证重复点击也能暂停并回到镜头起点。布局大小持久化，支持折叠、重置及键盘调整。

安装版所有可写状态默认位于 `%LOCALAPPDATA%/MotionReferenceAnalyzer`；`MRA_DATA_DIR` 可指定独立验收根。设置、会话、SQLite、资产、缓存、日志和导出与安装目录分离，内部资产使用 `@data/` 路径。

模型权重由用户在外部准备。模型页只读检测 Ollama 的本地安装与视觉能力，提供推荐和官网链接。PaddleOCR 校验显式目录的推理文件及 `inference.yml` 模型名，禁用未配置辅助模型。基础分析显式跳过视觉/OCR/排版语义；完整模式预检失败会拒绝执行。缓存包含模型内容身份和提示词版本。

项目支持未分析保存、稳定 ID、显示名修改、最近项目/镜头恢复，以及同 SHA256 素材重连。旧库导入使用只读 SQLite snapshot，暂存并校验引用资产，再以单事务导入空目标库，保留 ID 与标签。实现与验收见 `V1_0_COMPLETION_REPORT.md`。

## 总体结构

```text
┌──────────────────────────────────────┐
│              Tauri App               │
│  React UI                            │
│  - Video Player                      │
│  - Shot List                         │
│  - Timeline                          │
│  - Analysis Panel                    │
│  - AE Recipe Panel                   │
└──────────────────┬───────────────────┘
                   │ Local API / IPC
                   ▼
┌──────────────────────────────────────┐
│        Python Analysis Core          │
│  FastAPI + Uvicorn                   │
│  - Video Core                        │
│  - CV Core                           │
│  - OCR Core                          │
│  - AI Core                           │
│  - Recipe Core                       │
└──────────────────┬───────────────────┘
                   ▼
        Structured Shot JSON
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
   Markdown Report       Future LocalFX
```

## 模块职责

- `apps/desktop`: Tauri 2 + React 桌面 UI，负责视频导入、结果展示、导出触发。
- `core/app`: FastAPI 服务入口，暴露 REST API 供前端调用。
- `core/video`: 视频元数据、解码、分镜、代表帧采样。
- `core/vision`: 本地视觉语言模型统一接口与实现。
- `core/cv`: 光流、相机运动估计等客观运动分析。
- `core/ocr`: 文字检测与识别。
- `core/audio`: PyAV 音轨解码、librosa beat/onset、内容缓存与切镜节奏匹配；统一使用视频首帧为零点。
- `core/video/playback.py`: 非零原始时间戳媒体的本地播放副本，复制压缩包并归零时钟，不修改源视频。
- `core/recipe`: AE Recipe 生成与难度估算。
- `core/schemas`: Pydantic 数据模型与共享结构。
