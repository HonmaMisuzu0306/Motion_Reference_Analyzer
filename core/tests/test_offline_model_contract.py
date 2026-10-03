import sys
from types import SimpleNamespace

from models.ocr_paths import validate_ocr_models
from ocr.paddle_provider import PaddleOCRProvider
from schemas.settings import OCRModelPaths


def test_missing_models_do_not_construct_paddle(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(__version__="3.7.0", PaddleOCR=lambda **kw: calls.append(kw)),
    )
    paths = OCRModelPaths(
        language="ch", detection_dir=tmp_path / "det", recognition_dir=tmp_path / "rec"
    )
    result = validate_ocr_models([paths])
    assert not result.available
    provider = PaddleOCRProvider(languages=["ch"], model_paths=[paths])
    assert not provider.available
    assert calls == []


def test_all_engines_use_local_directories_and_no_aux_download(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(__version__="3.7.0", PaddleOCR=lambda **kw: calls.append(kw)),
    )
    for name in ["det", "rec"]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "inference.json").write_text("{}")
        (tmp_path / name / "inference.yml").write_text(f"Global:\n  model_name: PP-OCRv5_{name}\n")
        (tmp_path / name / "inference.pdiparams").write_bytes(b"test")
    paths = OCRModelPaths(
        language="ch", detection_dir=tmp_path / "det", recognition_dir=tmp_path / "rec"
    )
    provider = PaddleOCRProvider(languages=["ch"], model_paths=[paths])
    assert provider.available
    assert calls[0]["text_detection_model_dir"] == str(paths.detection_dir)
    assert calls[0]["text_recognition_model_dir"] == str(paths.recognition_dir)
    assert not calls[0]["use_textline_orientation"]


def test_local_model_names_override_new_paddle_defaults(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(__version__="3.7.0", PaddleOCR=lambda **kw: calls.append(kw)),
    )
    for directory, model in [
        ("renamed-det", "PP-OCRv5_server_det"),
        ("renamed-rec", "en_PP-OCRv5_mobile_rec"),
    ]:
        path = tmp_path / directory
        path.mkdir()
        (path / "inference.json").write_text("{}")
        (path / "inference.pdiparams").write_bytes(b"test")
        (path / "inference.yml").write_text(f"Global:\n  model_name: {model}\n")
    paths = OCRModelPaths(
        language="en",
        detection_dir=tmp_path / "renamed-det",
        recognition_dir=tmp_path / "renamed-rec",
    )
    provider = PaddleOCRProvider(languages=["en"], model_paths=[paths])
    assert provider.available
    assert calls[0]["text_detection_model_name"] == "PP-OCRv5_server_det"
    assert calls[0]["text_recognition_model_name"] == "en_PP-OCRv5_mobile_rec"


def test_missing_model_config_is_actionable_before_construction(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(__version__="3.7.0", PaddleOCR=lambda **kw: calls.append(kw)),
    )
    for directory in ["det", "rec"]:
        path = tmp_path / directory
        path.mkdir()
        (path / "inference.json").write_text("{}")
        (path / "inference.pdiparams").write_bytes(b"test")
    paths = OCRModelPaths(
        language="en", detection_dir=tmp_path / "det", recognition_dir=tmp_path / "rec"
    )
    result = validate_ocr_models([paths])
    assert not result.available
    assert "inference.yml" in result.errors[0]
    assert not PaddleOCRProvider(["en"], model_paths=[paths]).available
    assert not calls


def test_replacing_weights_in_same_directory_changes_cache_identity(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "paddleocr", SimpleNamespace(__version__="3.7.0", PaddleOCR=lambda **kw: None)
    )
    for name in ["det", "rec"]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "inference.json").write_text("{}")
        (tmp_path / name / "inference.yml").write_text(f"Global:\n  model_name: PP-OCRv5_{name}\n")
        (tmp_path / name / "inference.pdiparams").write_bytes(b"first")
    paths = OCRModelPaths(
        language="ch", detection_dir=tmp_path / "det", recognition_dir=tmp_path / "rec"
    )
    first = PaddleOCRProvider(languages=["ch"], model_paths=[paths]).get_model_info()
    (tmp_path / "rec/inference.pdiparams").write_bytes(b"other")
    second = PaddleOCRProvider(languages=["ch"], model_paths=[paths]).get_model_info()
    assert first != second
