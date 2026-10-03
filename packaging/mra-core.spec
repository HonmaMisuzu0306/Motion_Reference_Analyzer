from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas, binaries, hiddenimports = [], [], []
# PaddleX checks distribution metadata before constructing its OCR pipeline.
# Importable modules alone do not satisfy its ocr-core dependency check.
for dependency in ['imagesize', 'opencv-contrib-python', 'pyclipper',
                   'pypdfium2', 'python-bidi', 'shapely']:
    datas += copy_metadata(dependency)
# Package resources only: never collect user's HOME/cache or project output.
for package in ['paddle', 'paddleocr', 'paddlex', 'av', 'numba', 'llvmlite', 'scenedetect']:
    d, b, h = collect_all(package)
    datas += [(source, destination) for source, destination in d
              if not any(part.lower() in {'test','tests','__pycache__'} for part in Path(source).parts)]
    binaries += b
    hiddenimports += [name for name in h if not any(part in {'test','tests'} for part in name.split('.'))]
hiddenimports += collect_submodules('app') + collect_submodules('audio')
hiddenimports += collect_submodules('ocr') + collect_submodules('vision')
hiddenimports += collect_submodules('cv') + collect_submodules('db')
hiddenimports += collect_submodules('projects') + collect_submodules('models')
hiddenimports += collect_submodules('selection')
hiddenimports += collect_submodules('video') + collect_submodules('schemas') + collect_submodules('recipe')
a = Analysis([str(root/'packaging/runtime_entry.py')], pathex=[str(root/'core')],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['pytest', 'ruff', 'IPython', 'notebook', 'torch', 'tensorflow',
                       'transformers', 'sentence_transformers', 'test', 'tests'], noarchive=False)
a.datas = [entry for entry in a.datas if not any(part.lower() in {'test','tests','__pycache__'} for part in Path(entry[0]).parts)]
# Windows 10+ supplies API-set/UCRT system components. Do not bundle unsigned
# old SDK API-set forwarders accidentally found through a developer's PATH.
a.binaries = [entry for entry in a.binaries if not Path(entry[0]).name.lower().startswith('api-ms-win-') and Path(entry[0]).name.lower() != 'ucrtbase.dll']
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='mra-core', console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='mra-core')
