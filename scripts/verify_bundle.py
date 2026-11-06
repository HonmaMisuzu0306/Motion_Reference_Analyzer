"""Validate frozen inputs against known source roots, and audit installed resource names."""
import argparse
import ast
import hashlib
import json
import sys
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('bundle',type=Path)
args=parser.parse_args()
bundle=args.bundle.resolve()
assert (bundle/'mra-core.exe').is_file()
assert (bundle/'_internal').is_dir()
files=list(bundle.rglob('*'))
for path in files:
    if not path.is_file():continue
    assert path.name != '.env' and path.suffix.lower() not in {'.mp4','.mov','.mkv','.db','.sqlite','.log','.pdiparams','.safetensors','.gguf'},path
    assert not any(part.lower() in {'tests','test','__pycache__'} for part in path.relative_to(bundle).parts),path
allowed=[root/'core',Path(sys.base_prefix),root/'output/v1_build/freeze']
toc=ast.literal_eval((root/'output/v1_build/freeze/mra-core/COLLECT-00.toc').read_text(encoding='utf-8'))
inputs=[]
redistributables=[]
def visit(value):
    if isinstance(value,(list,tuple)):
        if len(value)==3 and isinstance(value[1],str) and isinstance(value[2],str) and value[2] in {'BINARY','DATA','EXECUTABLE','EXTENSION'}:
            source=Path(value[1]).resolve()
            if not any(source.is_relative_to(path.resolve()) for path in allowed):
                name=source.name.lower()
                assert value[2]=='BINARY' and (name in {'vcomp140.dll','vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll','ucrtbase.dll'} or (name.startswith('api-ms-win-') and name.endswith('.dll'))),f'Unapproved source: {source}'
                redistributables.append(str(source))
            assert not source.is_relative_to(root/'output') or source.is_relative_to(root/'output/v1_build/freeze'),source
            inputs.append({'destination':value[0],'source':str(source),'kind':value[2]})
        else:
            for item in value:visit(item)
visit(toc)
assert inputs,'No build source provenance found'
if redistributables:
    # Only Microsoft-signed compiler/runtime redistributables may come from PATH.
    command="$v1Dlls = ($input | Out-String | ConvertFrom-Json); foreach ($v1Dll in $v1Dlls) { $v1Signature = Get-AuthenticodeSignature -LiteralPath $v1Dll; if ($v1Signature.Status -ne 'Valid' -or $v1Signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw ('Untrusted runtime DLL: ' + $v1Dll) } }; Write-Output 'Microsoft redistributables verified'"
    verification=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',command],input=json.dumps(sorted(set(redistributables))),text=True,capture_output=True)
    assert verification.returncode==0,verification.stderr
report={'version':'1.10.0','files':sum(p.is_file() for p in files),'bytes':sum(p.stat().st_size for p in files if p.is_file()),
        'executable_sha256':hashlib.sha256((bundle/'mra-core.exe').read_bytes()).hexdigest(),'sources':inputs}
(root/'output/v1_build/runtime_provenance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in report.items() if key!='sources'}))
