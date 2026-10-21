"""Carga del modelo UNA sola vez al arrancar (lifespan), nunca por petición.

Si los archivos no están en MODEL_DIR, se descargan del bucket PRIVADO de Supabase
(MODEL_BUCKET/MODEL_PREFIX) a una carpeta temporal, se verifica su sha256 contra la ficha y solo
entonces se mueven a MODEL_DIR. Los nombres de archivo son FIJOS (nunca vienen de la ficha),
así que una ficha manipulada no puede escribir fuera de MODEL_DIR. Con MODEL_CARD_SHA256 se fija
además la huella de la propia ficha.
"""

import hashlib
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from backend.app.ml.config import ModelCard
from backend.app.ml.runtime import LiteRTPredictor, Predictor
from backend.app.ml.settings import MLSettings

logger = logging.getLogger(__name__)

CARD_FILE = "model_card.json"
# Únicos archivos que se descargan, verifican y cargan
REQUIRED_FILES = ("model.tflite", "head.npz")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class ModelUnavailableError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(directory: Path) -> ModelCard:
    """Valida ficha y archivos en `directory`; lanza ModelUnavailableError si algo no cuadra."""
    card_path = directory / CARD_FILE
    if not card_path.exists():
        raise ModelUnavailableError("Falta la ficha del modelo")
    pinned = os.environ.get("MODEL_CARD_SHA256")
    if pinned and _sha256(card_path) != pinned.lower():
        raise ModelUnavailableError("La ficha del modelo no coincide con MODEL_CARD_SHA256")
    card = ModelCard.load(card_path)
    if set(card.files) != set(REQUIRED_FILES):
        raise ModelUnavailableError(f"La ficha debe listar exactamente {REQUIRED_FILES}")
    for name in REQUIRED_FILES:
        expected = card.files[name]
        path = directory / name
        if not _SHA256.match(expected):
            raise ModelUnavailableError(f"Huella con formato inválido para {name}")
        if not path.is_file() or _sha256(path) != expected:
            raise ModelUnavailableError(f"Archivo del modelo ausente o alterado: {name}")
    return card


def _download(settings: MLSettings, model_dir: Path) -> None:
    """Descarga a un temporal, verifica y reemplaza MODEL_DIR (una descarga cortada no queda)."""
    from backend.app.services.storage import _get_client

    if not _PREFIX.match(settings.model_prefix):
        raise ModelUnavailableError("MODEL_PREFIX inválido")
    bucket = _get_client().storage.from_(settings.model_bucket)
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".descarga-", dir=model_dir.parent))
    try:
        for name in (CARD_FILE, *REQUIRED_FILES):
            (staging / name).write_bytes(bucket.download(f"{settings.model_prefix}/{name}"))
        _verify(staging)
        if model_dir.exists():
            shutil.rmtree(model_dir)
        os.replace(staging, model_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def ensure_model_files(settings: MLSettings) -> Path:
    model_dir = Path(settings.model_dir)
    try:
        _verify(model_dir)
    except ModelUnavailableError:
        logger.info("Modelo ausente o incompleto en disco; descargando del bucket privado")
        _download(settings, model_dir)
        _verify(model_dir)
    return model_dir


def load_predictor(settings: MLSettings) -> Predictor:
    model_dir = ensure_model_files(settings)
    # Se reverifica justo antes de cargar
    card = _verify(model_dir)
    predictor = LiteRTPredictor(model_dir, card)
    logger.info("Modelo cargado: %s (demo=%s)", card.model_version, card.is_demo)
    return predictor
