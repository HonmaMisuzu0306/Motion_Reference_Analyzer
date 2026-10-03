# V1.0 UI、图标、汉化与桌面发布调研

日期：2026-10-02。通过用户指定的 Firecrawl 插件完成多轮搜索与页面读取；外部请求仅包含公开资料查询，不上传本地视频、数据库或配置。

## 设计来源与落地方式

| 来源 | 本次查阅内容 | 用于 MRA 的决定 |
|---|---|---|
| [Adobe Workspaces, panels, and viewers](https://helpx.adobe.com/after-effects/desktop/get-started/get-familiar-with-the-interface/workspaces-panels-viewers.html) | 面板分组、工作区、布局保存/重置和预览组织 | 采用用户要求的 AE 风格：镜头/预览/详情/时间轴分区，可调整区域尺寸并恢复布局 |
| [Adobe 中文关键帧文档](https://helpx.adobe.com/cn/after-effects/desktop/animate-in-after-effects/animation-keyframes/setting-selecting-deleting-keyframes.html) | 搜索摘要中的时间轴、关键帧等行业中文用语 | 中文标签使用创作工具常见术语；此页仅检索摘要，不宣称阅读全文 |
| [Fluent Layout](https://fluent2.microsoft.design/layout) | 间距、分组、层级和响应布局 | 建立统一间距与对齐规则，预览占主空间；按窗口大小折叠侧栏 |
| [Fluent Color](https://fluent2.microsoft.design/color) | 中性色、品牌色和语义状态色的作用 | 深灰层级与有限选中强调；状态同时给文字/图形，避免只靠颜色 |
| [Windows app icon design](https://learn.microsoft.com/en-us/windows/apps/design/iconography/app-icon-design) | 简单隐喻、轮廓、小尺寸可读性和有限细节 | 原创取景框/运动轨迹标识；UI 图标采用统一几何规则 |
| [Ant Design 中文文案](https://ant.design/docs/spec/copywriting-cn/) | 表达清晰、名称一致、专业术语、错误下一步与标点 | 建立中文术语表；错误提供可操作路径；保留技术标识与原素材文本 |
| [Microsoft Localization Style Guides](https://learn.microsoft.com/en-us/globalization/reference/microsoft-style-guides) | 语言规范资源与简体中文指南入口 | 将本地化作为术语、日期/数字和显示格式的一致性工作；尚未读取入口所链接的完整简体中文指南 |

已读取的页面可能来自 Firecrawl 的近期索引/缓存，并非全部为实时获取；不以页面抓取成功推断任何产品功能已在本机运行。

## 产品实现资料

- [Tauri 2 Embedding External Binaries](https://v2.tauri.app/develop/sidecar/)：检索结果包含 externalBin、目标平台命名和 Rust 启动示例。拟用于应用管理本地分析核心；最终资源路径与退出处理仍需本地实现验证。
- [Tauri 2 Windows Installer](https://v2.tauri.app/distribute/windows-installer/)：读取 NSIS/MSI 的发行方式、Windows 构建及可配置选项。MRA 优先交付 Windows x64 NSIS 安装包。
- [Ollama List models](https://docs.ollama.com/api/tags)：检索摘要包含本地模型列表、名称和大小字段。用于模型页实际安装状态。
- [Ollama Pull a model](https://docs.ollama.com/api/pull)：早期读取下载请求和流式进度约定。用户随后明确改为自行下载，因此本接口不纳入 V1.0 实现；调研没有执行下载。

## 模型分发方案更新

用户明确要求“配置建议表 + 推荐模型 + 官网链接”，模型自行下载安装。2026-10-02再次调用 Firecrawl，并使用 `maxAge:0` 读取以下官方页面：

- [Qwen3-VL 官方 Ollama 模型页](https://ollama.com/library/qwen3-vl)：2b/4b/8b 标签均支持文本与图像，页面列出的模型文件大小分别约1.9/3.3/6.1GB。文件大小不是推理内存或显存需求。4b有本项目历史真实运行证据，2b/8b作为未验收候选；硬件配置阈值需在开发时验证。
- [Ollama Windows 下载页](https://ollama.com/download/windows)：提供用户安装运行服务的官方入口；MRA检测其本地连接和已安装模型。
- [PaddleOCR 官方 OCR 管线文档](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)：列有检测/识别推理模型下载链接与本地模型配置。页面当前也介绍PP-OCRv6；MRA继续使用已验证的PP-OCRv5组合，不据文档默认值变更自动升级。

设计改为本地模型/目录配置与验证，去掉 MRA 内置下载、下载进度和 pull 请求。所有模型权重排除在安装包之外，缺失模型也不触发 OCR 库的隐式下载。Python及分析引擎依赖作为应用运行组件，与模型权重明确区分。

## 开发前代码核对结果（历史基线）

Rust 入口尚未管理后端子进程；前端固定 API 端口；数据库和缓存依赖仓库路径；现有 Library 可复用项目/镜头/标签持久化；正常详情存在英文标题、枚举和原始 JSON。V1.0 的主要工作是产品界面、正常流程汉化、用户设置、项目恢复和独立桌面运行。

## 已排除的失败来源

第一次尝试的 Microsoft `/style-guide/global-communications/localization` 页面返回404，未用作设计依据；随后通过 Firecrawl 搜索定位到有效的 Globalization / Localization Style Guides 页面。

## 设计草案

详见 [MRA V1.0 设计草案](superpowers/specs/2026-10-02-mra-v1-design.md)。本调研记录为开发前依据，当前实现与验收见 [V1.0 交付记录](V1_0_COMPLETION_REPORT.md)。

开发验收中通过 Firecrawl 复读 [PaddleOCR 最新管线文档](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html)，与安装的 PaddleOCR 3.7 源码交叉核对：当指定本地目录时 lang/ocr_version 被忽略，默认管线已变为 v6。因此 MRA 显式读取目录配置的模型名称，并继续验证 PP-OCRv5；不自动切换模型或下载。
