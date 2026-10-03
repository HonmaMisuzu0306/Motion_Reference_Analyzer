# V1.0 构建

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
