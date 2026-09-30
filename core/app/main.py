import logging
import sys

from fastapi import FastAPI

from .api import router as api_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

app = FastAPI(
    title="Motion Reference Analyzer Core",
    version="0.1.0",
    description="本地视频参考分析与 AE 拆解服务",
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
