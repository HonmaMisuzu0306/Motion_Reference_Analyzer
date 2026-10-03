# Motion Reference Analyzer

面向静止画 MAD / Galgame OP / PV 创作者的镜头参考分析与 AE 拆解工具。

目标：将参考视频自动拆解为 **镜头时间轴、画面结构、运动信息、文字信息、效果推测与 AE 制作建议**，并为后续与 **LocalFX** 联动预留结构化接口。

## V1.0 Windows 桌面版

从 [GitHub Release v1.0.0](https://github.com/HonmaMisuzu0306/Motion_Reference_Analyzer/releases/tag/v1.0.0) 下载 `MRA-1.0.0-x64-setup.exe`，无需系统 Python/Node/Rust。支持 Windows 10/11 x64。
深灰工作台与原创图标、中文界面、项目恢复/重连、外部模型推荐与配置、基础分析及完整分析、参考库和导出已实现。
模型权重不随应用提供，由用户从“模型”页的官网入口自行取得；基础分析无需模型。

- [使用与外部模型准备](docs/V1_0_USAGE.md)
- [1.0 功能与验证范围](docs/RELEASE_v1.0.0.md)
- [源码构建](docs/V1_0_BUILD_GUIDE.md)

安装版数据默认保存在 `%LOCALAPPDATA%/MotionReferenceAnalyzer`。开发旧库不会被自动迁移，可在空库显式导入副本；源码开发命令继续见下方。

新增自选分析：点击“分析当前帧”即可分析准确画面，也可用上一帧/下一帧微调；设置入点/出点分析最长60秒片段。局部结果独立保存，可回看、重试和导出，不覆盖整片镜头结果。单帧只提供静态分析，片段少于8秒不估计BPM。

---

## 项目结构

```text
motion-reference-analyzer/
├─ apps/
│  └─ desktop/              # Tauri 2 + React + TypeScript 桌面端
├─ core/                    # Python 分析核心
│  ├─ app/                  # FastAPI 入口与 API
│  ├─ video/                # 视频元数据、解码、分镜、采样
│  ├─ vision/               # 本地 VLM 接口
│  ├─ cv/                   # 传统 CV 运动分析
│  ├─ ocr/                  # 文字识别与排版分析
│  ├─ recipe/               # AE Recipe 生成
│  ├─ schemas/              # Pydantic 数据模型
│  └─ tests/                # 单元测试
├─ docs/                    # 架构文档
├─ samples/                 # 示例视频
├─ output/                  # 项目输出
└─ scripts/                 # 脚本工具
```

---

## 快速开始

### Python 核心

```bash
cd core
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

或直接从项目根目录启动：

```bash
python scripts/start_server.py
```

### 前端

```bash
cd apps/desktop
npm install
npm run tauri dev
```

`scripts/start_server.py` 优先使用 `core/.venv` 的 Python。M6 音频依赖 librosa 随核心安装；前端本次已通过 TypeScript 与 Vite 构建验证。

### M6 音频节奏

导入含音轨的视频并点击“分析视频”，查看音频节奏面板中的 BPM、Beat/onset、切镜同步率及时间轴。点击镜头可定位播放并查看有符号的偏差；“重新分析音频”只重算音频，不调用视觉或 OCR 模型。

默认同步容差为 ±80ms。无音轨、静音、节拍不足会明确显示不可判断。JSON、Markdown、AE Recipe 与 Library 都保留节奏结果。V1.0 使用 schema6；时间原点无法确认的非零时间戳旧镜头需重新分析视频。

可复现的合成 MP4 验收：`core/.venv/Scripts/python.exe scripts/accept_audio.py`（Windows）。该脚本真实运行音频算法，Vision/OCR 使用 Mock，结果只写 `output/m6_acceptance` 的独立库。真实模型及局部分析验收入口见[构建说明](docs/V1_0_BUILD_GUIDE.md)。

---

## 核心原则

1. 先做可靠的数据流水线。
2. 传统算法解决能量化的问题。
3. VLM 解决语义问题。
4. 不让 AI 把“推测”写成“事实”。
5. 所有 AI 输出必须结构化。
6. 所有分析步骤必须可重试。
7. 所有昂贵步骤必须缓存。
8. MVP 不与 LocalFX 强耦合。

---

## 许可证

MIT
