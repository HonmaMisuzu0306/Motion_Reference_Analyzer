import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
VENV_PYTHON = PROJECT_ROOT / 'core' / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
PYTHON = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)


def main():
    cmd = [
        str(PYTHON),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--reload",
    ]
    raise SystemExit(subprocess.run(cmd, cwd=PROJECT_ROOT / "core", check=False).returncode)


if __name__ == "__main__":
    main()
