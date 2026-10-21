"""Cargador del modelo: verifica la huella de cada archivo antes de usarlo."""

import hashlib
import json

import pytest

from backend.app.ml.loader import ModelUnavailableError, ensure_model_files
from backend.app.ml.settings import MLSettings


def write_model(tmp_path, tamper: bool = False):
    content = b"modelo-falso"
    (tmp_path / "model.tflite").write_bytes(content + (b"x" if tamper else b""))
    card = {
        "model_version": "fake",
        "classes": ["normal", "benigno", "maligno"],
        "input_size": [224, 224],
        "preprocessing": "raw_0_255",
        "files": {"model.tflite": hashlib.sha256(content).hexdigest()},
    }
    (tmp_path / "model_card.json").write_text(json.dumps(card), encoding="utf-8")


def test_archivos_integros(tmp_path):
    write_model(tmp_path)
    assert ensure_model_files(MLSettings(model_dir=str(tmp_path))) == tmp_path


def test_archivo_alterado_se_rechaza(tmp_path):
    write_model(tmp_path, tamper=True)
    with pytest.raises(ModelUnavailableError, match="alterado"):
        ensure_model_files(MLSettings(model_dir=str(tmp_path)))


def test_archivo_faltante_se_rechaza(tmp_path):
    write_model(tmp_path)
    (tmp_path / "model.tflite").unlink()
    with pytest.raises(ModelUnavailableError):
        ensure_model_files(MLSettings(model_dir=str(tmp_path)))
