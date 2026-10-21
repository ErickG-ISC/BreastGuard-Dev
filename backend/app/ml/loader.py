"""Carga del modelo UNA sola vez al arrancar (lifespan), nunca por petición.

Si los archivos no están en MODEL_DIR, se descargan del bucket PRIVADO de Supabase
(MODEL_BUCKET/MODEL_PREFIX) y se verifica su sha256 contra la ficha antes de usarlos.
"""

import hashlib
import logging
from pathlib import Path

from backend.app.ml.config import ModelCard
from backend.app.ml.runtime import LiteRTPredictor, Predictor
from backend.app.ml.settings import MLSettings

logger = logging.getLogger(__name__)

CARD_FILE = "model_card.json"


class ModelUnavailableError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(settings: MLSettings, model_dir: Path) -> None:
    from backend.app.services.storage import _get_client

    bucket = _get_client().storage.from_(settings.model_bucket)
    model_dir.mkdir(parents=True, exist_ok=True)
    card_bytes = bucket.download(f"{settings.model_prefix}/{CARD_FILE}")
    (model_dir / CARD_FILE).write_bytes(card_bytes)
    for name in ModelCard.load(model_dir / CARD_FILE).files:
        (model_dir / name).write_bytes(bucket.download(f"{settings.model_prefix}/{name}"))


def ensure_model_files(settings: MLSettings) -> Path:
    model_dir = Path(settings.model_dir)
    if not (model_dir / CARD_FILE).exists():
        logger.info("Modelo no encontrado en disco; descargando del bucket privado")
        _download(settings, model_dir)
    card = ModelCard.load(model_dir / CARD_FILE)
    for name, expected in card.files.items():
        path = model_dir / name
        if not path.exists() or _sha256(path) != expected:
            raise ModelUnavailableError(f"Archivo del modelo ausente o alterado: {name}")
    return model_dir


def load_predictor(settings: MLSettings) -> Predictor:
    model_dir = ensure_model_files(settings)
    card = ModelCard.load(model_dir / CARD_FILE)
    predictor = LiteRTPredictor(model_dir, card)
    logger.info("Modelo cargado: %s (demo=%s)", card.model_version, card.is_demo)
    return predictor
