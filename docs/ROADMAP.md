# Roadmap

## V0.1

- Tauri UI
- 视频导入
- ffprobe / PyAV 元数据
- PySceneDetect 分镜
- Shot List
- 代表帧
- Timeline

## V0.2

- 本地 VLM
- Contact Sheet
- Shot JSON
- AE Recipe
- Markdown Export

## V0.3

- 光流分析
- 相机运动估计
- 运动置信度

## V0.4

- PaddleOCR
- Typography Analysis

## V0.5

- SQLite
- Reference Library
- Search / Tags

## V0.6

- Beat Detection — M6 已实现（librosa、本地音轨、内容缓存）
- Rhythm Analysis — M6 已实现（切镜节拍偏差、同步统计、时间轴、持久化与导出）
- 验收范围：真实算法处理合成 AAC/MP4；自然音乐节拍准确率尚未量化评估。V1.0原生发行及局部分析已完成验收，见[发行说明](RELEASE_v1.0.0.md)。

## V1.0

- 本地 Windows x64 桌面版：冻结分析核心随安装包运行；模型权重外置。
- AE 风格深灰工作台、原创图标、中文常规界面；镜头/预览/详情/音频时间轴协同。
- 中文 NSIS Installer、数据与安装目录分离、后台启动/退出/重试与实例身份校验。
- Model Management：推荐配置/官网链接、Ollama 只读检测与模型选择、外部 OCR 目录配置；不在 MRA 内下载模型。
- Project Management：未分析保存、显示名、最近项目恢复、内容校验重连、旧库副本导入，原 ID/标签保留。
- 当前实现、原生安装/模型分析与未验收范围见 [V1.0 发行说明](RELEASE_v1.0.0.md)。

## V1.5

- LocalFX Integration
- Send to LocalFX
- Shared AE Recipe Schema
# V1.0 自选分析扩展（2026-10-02）

已接入实际PTS单帧定位、静态分析、最长60秒半开片段分析、独立后台记录、回看、重试和局部导出。原整片分析保留，模型仍由用户外置安装。验证与交付状态见 [V1.0 发行说明](RELEASE_v1.0.0.md)。
