"""Owned desktop backend. Bind an OS-assigned loopback port; never reuse another server."""

import argparse
import json
import os
import socket
from pathlib import Path


def identity():
    return {
        "product": "mra",
        "version": "1.10.0",
        "protocol": 1,
        "instance_id": os.environ.get("MRA_INSTANCE_ID", "development"),
        "port": int(os.environ.get("MRA_PORT", "8000")),
        "pid": os.getpid(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MRA_DATA_DIR"] = str(args.data_dir.resolve())
    os.environ["MRA_INSTANCE_ID"] = args.instance_id
    # Release never inherits a mock provider or reads a working-directory .env.
    os.environ["VISION_PROVIDER"] = "qwen3-vl"
    os.environ["OCR_PROVIDER"] = "paddleocr"
    os.environ["REQUIRE_LOCAL_OCR_MODELS"] = "true"
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    if args.probe:
        import av
        import cv2
        import librosa
        import numba
        import paddle
        from paddleocr import PaddleOCR

        print(
            json.dumps(
                {
                    "av": av.__version__,
                    "opencv": cv2.__version__,
                    "librosa": librosa.__version__,
                    "numba": numba.__version__,
                    "paddle": paddle.__version__,
                    "ocr": PaddleOCR.__name__,
                }
            )
        )
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    os.environ["MRA_PORT"] = str(sock.getsockname()[1])
    import uvicorn

    from app.main import app

    class DesktopServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                print("MRA_READY " + json.dumps(identity()), flush=True)

    DesktopServer(uvicorn.Config(app, log_level="info", access_log=False)).run(sockets=[sock])


if __name__ == "__main__":
    main()
