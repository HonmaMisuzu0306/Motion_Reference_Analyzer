import json
import os
import subprocess
import sys
from pathlib import Path

import httpx


def test_owned_backend_dynamic_port_and_identity(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1]), "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.bootstrap",
            "--data-dir",
            str(tmp_path / "中文 数据"),
            "--port",
            "0",
            "--instance-id",
            "test-owned",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stdout.readline()
        assert line.startswith("MRA_READY "), (
            process.stderr.read() if process.poll() is not None else line
        )
        ready = json.loads(line.removeprefix("MRA_READY "))
        assert ready["instance_id"] == "test-owned"
        assert ready["product"] == "mra" and ready["version"] == "1.10.1"
        response = httpx.get(f"http://127.0.0.1:{ready['port']}/health", trust_env=False)
        assert response.json() == {**ready, "status": "ok"}
        assert ready["pid"] > 0
    finally:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            process.terminate()
        process.wait(timeout=15)
