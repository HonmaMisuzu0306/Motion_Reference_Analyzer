import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from selection.api import router as selection_router
from selection.api import startup_recover

from .api import router as api_router
from .model_api import router as model_router
from .project_api import router as project_router
from .settings_api import router as settings_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
    ],
)

@asynccontextmanager
async def lifespan(app):
    startup_recover()
    yield


app = FastAPI(
    title="Motion Reference Analyzer Core",
    version="1.0.0",
    description="本地视频参考分析与 AE 拆解服务",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(model_router, prefix="/api/v1")
app.include_router(project_router, prefix="/api/v1")
app.include_router(selection_router, prefix="/api/v1")
app.add_middleware(CORSMiddleware,
    allow_origins=["tauri://localhost", "http://tauri.localhost"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Range"], expose_headers=["Content-Range", "Accept-Ranges"])


@app.get("/health")
def health():
    from app.bootstrap import identity
    return {'status': 'ok', **identity()}
