import importlib.util

from fastapi import APIRouter

from app.settings import SettingsStore
from models.catalog import recommendations
from models.ocr_paths import discover_ocr_models, validate_ocr_models
from models.ollama import OllamaInspector

router = APIRouter()


@router.get("/models/recommendations")
def catalog():
    ram = None
    try:
        import psutil

        ram = psutil.virtual_memory().total
    except ImportError:
        pass
    return {
        "recommendations": recommendations(),
        "hardware": {"ram_bytes": ram, "gpu_name": None, "vram_bytes": None},
        "ollama_download_url": "https://ollama.com/download/windows",
    }


@router.get("/models/status")
def status():
    settings = SettingsStore().load()
    ocr = validate_ocr_models(settings.ocr_models)
    result = OllamaInspector(settings.ollama_url).inspect()
    result["selected_model"] = settings.qwen_model_id
    result["ocr"] = {
        "engine_installed": importlib.util.find_spec("paddleocr") is not None,
        "available": ocr.available,
        "configured": bool(settings.ocr_models),
        "discovered_models": discover_ocr_models(),
        "errors": ocr.errors,
    }
    return result
