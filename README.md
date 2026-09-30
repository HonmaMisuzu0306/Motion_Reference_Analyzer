# Motion Reference Analyzer

面向静止画 MAD / Galgame OP / PV 创作者的镜头参考分析与 AE 拆解工具。

目标：将参考视频自动拆解为 **镜头时间轴、画面结构、运动信息、文字信息、效果推测与 AE 制作建议**，并为后续与 **LocalFX** 联动预留结构化接口。

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

注意：当前沙箱环境中 `npm install` 会被安全策略终止（SIGTERM），前端源码与配置已就绪，可在允许 npm 网络访问的环境中继续完成安装。

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
