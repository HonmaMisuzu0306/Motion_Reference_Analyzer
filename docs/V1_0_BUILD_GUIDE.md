# V1.0 构建

v1.10.0 发布修订构建使用 Python 3.13.7、PyAV 19.0.2、Starlette 1.10.0。完整依赖版本与许可随本版第三方说明包提供。下文保留早期构建与验收记录。

v1.1.0 本地安装包使用 Python 3.12.14、PyInstaller 6.22.3 构建。NSIS 对输入文件路径有长度限制，建议将源码解压到简短目录（例如 `E:\MRA`）；内存紧张时设置 `$env:CARGO_BUILD_JOBS='1'`。冻结配置会保留构建 Python 随附的 SSL 信任策略文件，避免冻结程序加载网络组件时缺失资源。

在 Windows x64 上准备 Node/npm、Rust/MSVC 和项目 Python 3.13 虚拟环境。
分析依赖包含 PaddlePaddle 3.3.1、PaddleOCR 3.7.0、PP-OCRv5 接口、PyAV/OpenCV/librosa/Numba。
开发构建需 PyInstaller 6.22.3、PowerShell 7（`pwsh`，验证 Microsoft DLL 签名）；模型权重保持在用户外部目录。

首次准备环境（在仓库根目录执行）：

```powershell
py -3.13 -m venv core/.venv
core/.venv/Scripts/python.exe -m pip install -e "./core[dev,ocr]" pyinstaller==6.22.3
cd apps/desktop
npm ci
cd ../..
```

发行源码附有npm与Rust锁文件；Python构建依赖实际版本记录在Release的第三方说明压缩包中。重新解析Python依赖可能得到不同版本，不能承诺安装器逐字节复现。

仅运行核心回归测试时，可安装 `pip install -e "./core[dev]"`，不需要 OCR 模型或
`[ocr]` 依赖。API 测试会在 pytest 临时目录生成视频，OCR 适配测试仅替换原生模型
和对应版本元数据；不依赖未跟踪的 `samples/test_typography.mp4`，也不访问用户模型。
人工执行 `scripts/accept_real_ocr.py` 前仍需运行 `scripts/generate_typography_sample.py`
并配置真实模型。Windows 后台启动测试需要允许结束它自己启动的子进程树。

```powershell
cd C:\Motion_Reference_Analyzer
core\.venv\Scripts\python.exe -m pytest core\tests -q
core\.venv\Scripts\python.exe -m ruff check core
cd apps\desktop
npm install
npm run test
npm run build
cargo test --manifest-path src-tauri\Cargo.toml
cd ..\..
scripts\build_installer.ps1
```

构建脚本先冻结核心，再校验资源来源，最后生成 NSIS 安装器。
输出核心位于 `output/v1_build/runtime/mra-core`，安装器位于
`apps/desktop/src-tauri/target/release/bundle/nsis`。
正在使用生成运行时的本次验收进程必须先正常退出，否则 Windows 会锁定 DLL，构建失败。
不要根据进程名关闭用户正在使用的服务。

`packaging/runtime_manifest.json` 声明资源范围；`verify_bundle.py` 检查 COLLECT TOC 来源与产物禁入项。
只接受项目源包、venv/标准库、PyInstaller 产物及经 Microsoft 签名验证的编译器运行 DLL。
Windows 10+ 已提供 API-set/UCRT 系统组件，不打包通过开发 PATH 偶然找到的旧 API-set 转发 DLL。
不收集用户 HOME 模型缓存、.env、视频、数据库、日志与测试夹具。
产物来源和 SHA256 记录在 `output/v1_build/runtime_provenance.json`，仅作为本地构建证据。

独立运行时验收：

```powershell
core\.venv\Scripts\python.exe scripts\accept_v1.py --executable output\v1_build\runtime\mra-core\mra-core.exe --video output\m6_acceptance\rhythm_120bpm.mp4 --data-dir output\v1_acceptance\fresh
```

验收在指定独立工作目录执行冻结服务，清除 Python/venv 环境入口，使用 OS 分配的端口。
独立安装验收还需实际操作原生文件选择、关闭/恢复、异常重试、更新及卸载保留数据。
PaddleX 的 `ocr-core` 会检查六项依赖的 distribution metadata，spec 显式收集这些版本信息。
PaddleOCR 3.7 的默认模型已变为 v6；指定外部目录时必须从 `inference.yml` 读取真实模型名称，不能仅设置 `ocr_version`。
局部分析的合成视频真实模型验收：

```powershell
core/.venv/Scripts/python.exe scripts/accept_selection.py --help
```

本版安装器未进行代码签名；GitHub Release同时提供SHA256校验文件及第三方说明。校验下载文件后按Windows正常安装流程操作。

## 开发版轨迹与 AE 试作验证（未发布）

当前源码增加 `spatial-affine-v4` 分镜、真实 PTS 运动矩阵轨迹、分段显示、带容差的 AE 曲线和 JSX 导出。
这些变化未包含在上方既有 V1.0.0 安装器内。版本与字段见 [JSON Schema](JSON_SCHEMA.md)，
操作与测量限制见 [AE 运动流程](AE_MOTION_WORKFLOW.md)。

从仓库根目录运行核心定向检查和真实编码的合成基准：

```powershell
core/.venv/Scripts/python.exe -m pytest core/tests/test_cv_cache_identity.py core/tests/test_analysis_source_identity.py core/tests/test_motion_trajectory.py core/tests/test_motion_curves.py core/tests/test_recipe_evidence.py core/tests/test_ae_script.py core/tests/test_scene_detect.py core/tests/test_scene_benchmark.py -q
core/.venv/Scripts/python.exe -m pytest core/tests/test_motion_quality.py core/tests/test_cv_streaming.py core/tests/test_audio_source_identity.py core/tests/test_audio.py core/tests/test_audio_pipeline.py -q
core/.venv/Scripts/python.exe scripts/benchmark_scenes.py --output-dir output/scene-benchmark --tolerance 0.05 --fps 24
core/.venv/Scripts/python.exe scripts/benchmark_motion.py --output-dir output/motion-benchmark --width 320 --height 180 --fps 24 --duration 3 --target-fps 8
```

两条基准命令会在指定目录生成独立合成 MP4 与 `report.json`；不需要用户参考视频或真实 VLM/OCR 模型。
分镜默认运行 11 类，运动默认运行 10 类×整片/选区共 20 个区间。可用 `--help` 查看单类选择。
不要把生成媒体或大报告提交到源码仓库；保存报告时同时记录当前代码版本、参数和运行环境。
后续算法更新应重新生成报告，不能将旧数字当作新版本的测试结果。

本轮分镜报告在 ±50ms 容差下，整片与选区均为 **TP=6、FP=0、FN=0**；最终 CV quality-v4 运动报告有 16 个连续区间、
2 个遮挡分段区间、2 个低纹理不可测区间。详细误差和缺失覆盖见 [基准说明](AE_MOTION_WORKFLOW.md#运动基准)。
这些是合成平面运动/硬切实验，**不是自然视频准确率**；叠化在分镜基准中没有标成硬切，结果也不验证叠化召回率。

缓存回归需覆盖同名、同大小、同 mtime 的替换源、相同内容跨路径、亚毫秒时间边界、损坏/失败记录、原子写入失败。
分析入口在每次请求验证 SHA256，在发布结果前复核源身份；不能为减少计算跨请求信任文件属性。
长视频性能检查应区分像素帧缓存与轻量轨迹数据，测量峰值内存，避免把所有解码帧常驻内存。
质量检查应区分特征跟踪可靠性与运动平滑性；快速往返或加速本身不能直接判成错误跟踪。

音频身份回归会在实际 WAV 解码期间替换同路径、同大小、同 mtime 的文件，并检查缓存读取期间替换和源文件丢失。
旧实现的定向复现为 8 失败/1 通过；修复后新增 12 项与已有音频/流水线合计 **28 项通过**，相关文件 ruff 检查通过。
音频缓存命名空间更新为 `audio-source-verified-v1`；`analyze_audio` 每次正常调用验证两次内容身份，且命中时不重新解码。
API 为确认音频属于当前项目还会执行额外校验，这不是整条 HTTP 请求的两次哈希上限。
这些检查不验证真实音乐的节拍准确率，也不替代前述真实模型与安装器验收。

来源替换验收还应检查导入、整片分析、音频重试和手动保存：最终复核失败时，旧镜头、旧音频和旧素材路径保持可回看；
候选结果及待发布 CV/OCR 缓存不得先行成为正式结果。整片 OCR 待发布缓存版本为 `v4-actual-pts-verified-source`。
原视频缺失时保存仍需保留已有 source_hash；文件被替换时应收到 409，不能按当前路径重新给旧分析赋新身份。
短镜头检查应使用原始时间精度，确认 CV 节奏的浮点容差没有放宽半开范围边界。

前端验证仍使用 `apps/desktop` 下的 `npm test` 与 `npm run build`。
界面检查至少包含往返曲线、部分跟踪、旧记录、非法数值、关键帧分页，以及主工作区/参考库/选区三处导出。
确认时间轴注明源视频秒或镜头局部秒，图表不跨缺口连线，导出失败能保留原因并重试。

### JSX 合同检查与真实 AE 验收

`core/tests/test_ae_script.py` 使用 `node` 执行生成的 JSX，AE 对象由 `core/tests/fixtures/ae_mock.cjs` 提供。
请保证 Node 在 PATH 中；缺少 Node 时这些执行用例会跳过，不能把跳过记成已完成验收。
该检查验证调用合同、真实局部时间、像素换算、独立合成和线性插值，不验证真实 ExtendScript 或渲染画面。

本轮真实 AE bridge 不在线，**尚未完成真实 AE 验收**。可用真实 AE 后，应按以下步骤补验：

1. 从当前工作镜头、参考库镜头和已完成片段各导出一份合格 JSX，并验证语义/静止/断续记录被拒绝。
2. 在 AE 工程中通过 File > Scripts > Run Script File 运行，检查新建 `CONTENT` 与 `MOTION`，核对尺寸、FPS、局部关键帧时间和工作区。
3. 用同尺寸静态素材替换标记，分别核对平移、缩放、旋转、复合与往返；采样覆盖之外的端点保持不得当作测量结果。
4. 验证无父层二维、中心锚点前提，检查当前选中层和已有工程内容未被改动，撤销一次可移除本次试作。
5. 记录 AE 版本、截图/短预览、运动偏差和失败原因，完成后才可声明该 AE 环境已验收。

真实 VLM、OCR 和本轮安装器同样尚未验收。它们仍需外部真实模型、冻结运行时及 Windows 原生安装/卸载流程的独立检查；
基础分析、模型替身测试与合成视频基准不能替代这些检查。
