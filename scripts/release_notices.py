"""Save actual build versions and available upstream license texts for local delivery."""
import ast
import importlib.metadata as metadata
import json
import shutil
import sys
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
release = root / 'output/v1_release'
release.mkdir(parents=True, exist_ok=True)
source_files = set()
def collect(value):
    if isinstance(value, (tuple, list)):
        if len(value) == 3 and isinstance(value[1], str) and value[2] in {'BINARY','DATA','PYMODULE','EXTENSION'}:
            source_files.add(Path(value[1]).resolve())
        else:
            for child in value: collect(child)
collect(ast.literal_eval((root/'output/v1_build/freeze/mra-core/Analysis-00.toc').read_text(encoding='utf-8')))
python = []
for dist in metadata.distributions():
    name = dist.metadata['Name']
    files = dist.files or []
    included = any(Path(dist.locate_file(file)).resolve() in source_files for file in files)
    if not included: continue
    python.append({'name': name, 'version': dist.version,
                   'license': dist.metadata.get('License-Expression') or dist.metadata.get('License') or '',
                   'license_classifiers': [c for c in dist.metadata.get_all('Classifier', []) if c.startswith('License ::')],
                   'urls': dist.metadata.get_all('Project-URL', [])})
    for file in files:
        if 'license' in file.name.lower() or 'copying' in file.name.lower() or 'notice' in file.name.lower():
            source = Path(dist.locate_file(file))
            if source.is_file() and source.suffix.lower() not in {'.py','.pyc','.pyd','.dll'}:
                destination = release/'licenses'/f'{name}-{dist.version}'/file
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
python.sort(key=lambda item: item['name'].lower())
python_license = Path(sys.base_prefix)/'LICENSE.txt'
if python_license.is_file():
    shutil.copy2(python_license, release/'licenses/Python-LICENSE.txt')
npm = json.loads((root/'apps/desktop/package-lock.json').read_text(encoding='utf-8'))
rust = tomllib.loads((root/'apps/desktop/src-tauri/Cargo.lock').read_text(encoding='utf-8'))
manifest = {'version':'1.10.1', 'python':sys.version, 'frozen_python_distributions':python,
            'npm_build_lock':npm, 'rust_build_lock':rust,
            'scope':'Python rows matched frozen Analysis sources; npm/Rust include build graphs, not a claim that every entry is shipped.'}
(release/'BUILD_DEPENDENCIES.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),encoding='utf-8')
rows = '\n'.join(f"| {item['name']} | {item['version']} | {(item['license'] or '; '.join(item['license_classifiers']) or '见上游 metadata').replace(chr(10),' ')[:120]} |" for item in python)
notice = f'''# MRA 1.10.1 第三方说明

本项目源码声明 MIT。分析运行时使用 Python 及下表组件；版本来自当前构建环境，并与冻结 Analysis 输入对应。
可获得的上游许可文本保存在本目录的 `licenses/`，详细 metadata、npm 和 Rust 构建锁保存在 `BUILD_DEPENDENCIES.json`。
npm/Rust 锁包含构建依赖，不能据此认为所有条目都进入安装包。模型权重不随应用交付，用户自行取得时应参照各模型的上游许可。

| Python 组件 | 当前版本 | 上游许可 metadata 摘要 |
| --- | --- | --- |
{rows}

前端使用 React（MIT）；桌面使用 Tauri（MIT/Apache-2.0），图标由本项目原创。
PyAV wheel 所包含 FFmpeg 组件的版本/许可证由其随附上游许可文本说明；不将项目 MIT 许可推广为第三方许可。
Windows WebView2 为 Microsoft 系统组件；安装器使用 NSIS，编译器运行库只接受已验证的 Microsoft 签名 DLL。

参考：[React](https://github.com/facebook/react/blob/main/LICENSE)、[Tauri](https://github.com/tauri-apps/tauri)、[PyAV](https://github.com/PyAV-Org/PyAV)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)。
'''
(release/'THIRD_PARTY_NOTICES.md').write_text(notice, encoding='utf-8')
print(f'Saved {len(python)} frozen Python distribution notices and build locks')
