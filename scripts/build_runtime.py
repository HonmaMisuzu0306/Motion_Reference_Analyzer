"""Reproducible package-source build; no user data in distribution inputs."""
import argparse
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=root/'output/v1_build/runtime')
args = parser.parse_args()
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath',
                str(args.output), '--workpath', str(root/'output/v1_build/freeze'),
                str(root/'packaging/mra-core.spec')], cwd=root, check=True)
