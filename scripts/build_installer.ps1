$ErrorActionPreference = 'Stop'
$v1ProjectRoot = Split-Path -Parent $PSScriptRoot
& "$v1ProjectRoot\core\.venv\Scripts\python.exe" "$PSScriptRoot\build_runtime.py"
if ($LASTEXITCODE -ne 0) { throw '运行时构建失败' }
& "$v1ProjectRoot\core\.venv\Scripts\python.exe" "$PSScriptRoot\verify_bundle.py" "$v1ProjectRoot\output\v1_build\runtime\mra-core"
if ($LASTEXITCODE -ne 0) { throw '资源清单校验失败' }
Push-Location "$v1ProjectRoot\apps\desktop"
try { & npm run tauri build -- --bundles nsis; if ($LASTEXITCODE -ne 0) { throw '安装器构建失败' } }
finally { Pop-Location }
