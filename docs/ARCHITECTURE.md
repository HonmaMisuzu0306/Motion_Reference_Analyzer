# Architecture

Motion Reference Analyzer 采用桌面端 + Python 分析核心的分层架构。

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
- `core/recipe`: AE Recipe 生成与难度估算。
- `core/schemas`: Pydantic 数据模型与共享结构。
