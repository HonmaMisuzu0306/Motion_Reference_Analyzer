import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PYTHON = Path(r"C:\Users\12723\.workbuddy\binaries\python\envs\default\Scripts\python.exe")


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
    subprocess.run(cmd, cwd=PROJECT_ROOT / "core")


if __name__ == "__main__":
    main()
