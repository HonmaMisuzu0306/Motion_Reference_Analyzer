import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from schemas.settings import OCRModelPaths


def local_model_name(directory: Path) -> str:
    """Use the exported model identity, independent of the directory's name."""
    try:
        config = yaml.safe_load((Path(directory) / "inference.yml").read_text(encoding="utf-8"))
        name = config["Global"]["model_name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Global.model_name 为空")
        return name
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise ValueError(
            f"模型目录缺少或无法读取 inference.yml 的 Global.model_name：{directory}"
        ) from exc


def model_identity(models: list[OCRModelPaths]) -> str:
    digest = hashlib.sha256()
    for row in models:
        digest.update(row.model_dump_json().encode("utf-8"))
        for directory in [row.detection_dir, row.recognition_dir, row.orientation_dir]:
            if not directory:
                continue
            for file in sorted(Path(directory).glob("inference.*")):
                digest.update(file.name.encode())
                with file.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
    return digest.hexdigest()


@dataclass
class OCRValidation:
    available: bool
    errors: list[str]


def validate_ocr_models(models: list[OCRModelPaths]) -> OCRValidation:
    errors = []
    if not models:
        errors.append("尚未选择 OCR 模型目录；请在模型页检测并选用本机已有模型，或在设置中选择目录")
    for row in models:
        for title, path in [
            ("检测", row.detection_dir),
            ("识别", row.recognition_dir),
            ("方向", row.orientation_dir),
        ]:
            if path is None:
                continue
            path = Path(path)
            if (
                not path.is_dir()
                or not (path / "inference.pdiparams").is_file()
                or not any(
                    (path / file).is_file() for file in ["inference.json", "inference.pdmodel"]
                )
            ):
                errors.append(f"{row.language} {title}模型目录缺少推理文件：{path}")
            else:
                try:
                    local_model_name(path)
                except ValueError as exc:
                    errors.append(f"{row.language} {title}：{exc}")
    return OCRValidation(not errors, errors)


def discover_ocr_models(cache_root: Path | None = None) -> list[dict]:
    """Inspect known local PaddleX exports without initializing or downloading models."""
    root = cache_root if cache_root is not None else Path.home() / '.paddlex' / 'official_models'
    detection = None
    for name in ['PP-OCRv5_server_det', 'PP-OCRv5_mobile_det']:
        directory = root / name
        try:
            if (local_model_name(directory) == name
                    and (directory / 'inference.pdiparams').is_file()
                    and any((directory / file).is_file()
                            for file in ['inference.json', 'inference.pdmodel'])):
                detection = directory
                break
        except ValueError:
            continue
    if detection is None:
        return []
    found = []
    for name, label, languages in [
        ('PP-OCRv5_server_rec', 'PP-OCRv5 通用识别（服务器版）', ['ch', 'japan', 'en']),
        ('PP-OCRv5_mobile_rec', 'PP-OCRv5 通用识别（轻量版）', ['ch', 'japan', 'en']),
        ('en_PP-OCRv5_mobile_rec', 'PP-OCRv5 英文识别（轻量版）', ['en']),
    ]:
        recognition = root / name
        row = OCRModelPaths(language=languages[0], detection_dir=str(detection),
                            recognition_dir=str(recognition))
        if not validate_ocr_models([row]).available:
            continue
        if local_model_name(recognition) != name:
            continue
        found.append({'label': label, 'languages': languages,
                      'detection_dir': str(detection), 'recognition_dir': str(recognition)})
    return found
