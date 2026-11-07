"""Ficha del modelo (`model_card.json`): única fuente de clases, tamaño y preprocesamiento.

Tarjeta v2 (ADR 0014): además, calibración de la confianza, versión del preprocesamiento
compartido (ml/preprocess.py) y datos informativos (entrenamiento, métricas, limitaciones) que
se publican en "Acerca del modelo". Todo lo nuevo es opcional y, si viene, se valida: una ficha
con un valor inválido NO carga (el modelo queda `unavailable`, falla cerrado).
"""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.app.ml.preprocess import MODES as PREPROCESSING_MODES
from backend.app.ml.preprocess import PREPROCESSING_VERSION

# Nombres canónicos de la app. El modelo puede ser de 2 clases (benigno/maligno) o de 3
# (normal/benigno/maligno); se aceptan los nombres en inglés de BUSI.
CANONICAL = ("normal", "benigno", "maligno")
ALIASES = {
    "normal": "normal",
    "benign": "benigno",
    "benigno": "benigno",
    "malignant": "maligno",
    "maligno": "maligno",
}
# Fuera de este rango la temperatura es casi seguro un error de exportación
TEMPERATURE_RANGE = (0.05, 20.0)
TEXT_MAX = 2000
MAX_LIMITATIONS = 30
# model_version es también el prefijo del bucket: el mismo formato que loader._PREFIX
MODEL_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
# Claves de training/metrics: cortas y sin espacios (se publican; no son texto libre)
KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
MAX_KEYS = 30


class ModelCardError(ValueError):
    pass


@dataclass(frozen=True)
class Calibration:
    method: str  # solo "temperature"
    temperature: float

    def apply(self, probabilities: np.ndarray) -> np.ndarray:
        """p_i ∝ p_i^(1/T): equivale a softmax(z/T) sobre los logits z del modelo."""
        if self.temperature == 1.0:
            return probabilities
        logp = np.log(np.clip(np.asarray(probabilities, dtype=np.float64), 1e-12, 1.0))
        logp = logp / self.temperature
        logp -= logp.max()
        scaled = np.exp(logp)
        return scaled / scaled.sum()


IDENTITY = Calibration("temperature", 1.0)


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > TEXT_MAX:
        raise ModelCardError(f"{field} debe ser un texto de 1 a {TEXT_MAX} caracteres")
    return value.strip()


def _optional_text(value, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ModelCardError(f"{field} debe ser un número finito")
    return float(value)


def _keys(data: dict, field: str) -> None:
    if len(data) > MAX_KEYS or any(not KEY.match(str(k)) for k in data):
        raise ModelCardError(f"{field}: hasta {MAX_KEYS} claves en snake_case de 1 a 41 caracteres")


def _calibration(data) -> Calibration:
    if data is None:
        return IDENTITY
    if not isinstance(data, dict) or data.get("method") != "temperature":
        raise ModelCardError("Calibración no soportada (solo method=temperature)")
    temperature = _number(data.get("temperature"), "calibration.temperature")
    low, high = TEMPERATURE_RANGE
    if not low <= temperature <= high:
        raise ModelCardError(f"La temperatura debe estar entre {low} y {high}")
    return Calibration("temperature", temperature)


def _canonical(name, field: str) -> str:
    try:
        return ALIASES[str(name).lower()]
    except KeyError:
        raise ModelCardError(f"{field}: clase desconocida {name!r}") from None


def _metrics(data, classes: tuple[str, ...]) -> dict | None:
    """Métricas de PRUEBA: números, por clase o globales, y la matriz de confusión."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ModelCardError("metrics debe ser un objeto")
    _keys(data, "metrics")
    out: dict = {}
    for key, value in data.items():
        key = str(key)
        if key == "confusion_matrix":
            n = len(classes)
            if (
                not isinstance(value, list)
                or len(value) != n
                or any(not isinstance(row, list) or len(row) != n for row in value)
            ):
                raise ModelCardError("confusion_matrix debe ser de clases × clases")
            cells = [[_number(v, key) for v in row] for row in value]
            if any(v < 0 or v != int(v) for row in cells for v in row):
                raise ModelCardError("confusion_matrix debe tener conteos enteros")
            out[key] = [[int(v) for v in row] for row in cells]
        elif key == "per_class":
            if not isinstance(value, dict):
                raise ModelCardError("metrics.per_class debe ser un objeto")
            per_class = {}
            for cls, values in value.items():
                if not isinstance(values, dict):
                    raise ModelCardError("metrics.per_class debe tener objetos por clase")
                _keys(values, "metrics.per_class")
                per_class[_canonical(cls, "metrics.per_class")] = {
                    str(m): _number(v, f"metrics.per_class.{cls}.{m}") for m, v in values.items()
                }
            out[key] = per_class
        elif key == "test_set":
            out[key] = _text(value, "metrics.test_set")
        else:
            out[key] = _number(value, f"metrics.{key}")
    return out


def _training(data) -> dict | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ModelCardError("training debe ser un objeto")
    _keys(data, "training")
    out = {}
    for key, value in data.items():
        if isinstance(value, bool):
            out[str(key)] = value
        elif isinstance(value, int | float):
            out[str(key)] = _number(value, f"training.{key}")
        else:
            out[str(key)] = _text(value, f"training.{key}")
    return out


def _thresholds(data) -> dict | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ModelCardError("recommended_thresholds debe ser un objeto")
    _keys(data, "recommended_thresholds")
    return {str(k): _number(v, f"recommended_thresholds.{k}") for k, v in data.items()}


@dataclass(frozen=True)
class ModelCard:
    model_version: str
    is_demo: bool
    classes: tuple[str, ...]  # canónicos, en el ORDEN de salida del modelo
    input_size: tuple[int, int]
    color_mode: str
    preprocessing: str
    files: dict[str, str]  # nombre -> sha256
    # Tarjeta v2 (ADR 0014)
    preprocessing_version: int | None = None
    calibration: Calibration = IDENTITY
    description: str | None = None
    intended_use: str | None = None
    training: dict | None = None
    metrics: dict | None = None
    limitations: tuple[str, ...] = ()
    # Solo informativo: los umbrales vigentes están en MLSettings y nunca se toman de aquí
    recommended_thresholds: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ModelCard":
        try:
            classes = tuple(ALIASES[name.lower()] for name in data["classes"])
        except KeyError as exc:
            raise ModelCardError(f"Clase desconocida en la ficha: {exc}") from None
        if len(classes) not in (2, 3) or len(set(classes)) != len(classes):
            raise ModelCardError("El modelo debe tener 2 o 3 clases distintas")
        if data.get("preprocessing") not in PREPROCESSING_MODES:
            raise ModelCardError(f"Preprocesamiento no soportado: {data.get('preprocessing')}")
        if data.get("color_mode", "rgb") not in ("rgb", "grayscale"):
            raise ModelCardError("color_mode debe ser rgb o grayscale")
        is_demo = bool(data.get("is_demo", False))
        version = data.get("preprocessing_version")
        if version is None and not is_demo:
            # Un modelo real sin versión de preprocesamiento: no se sabe con qué se entrenó
            raise ModelCardError("Falta preprocessing_version en la ficha de un modelo real")
        if version is not None and (isinstance(version, bool) or version != PREPROCESSING_VERSION):
            raise ModelCardError(
                f"preprocessing_version {version!r} no coincide con la del servidor "
                f"({PREPROCESSING_VERSION}): el modelo se entrenó con otro preprocesamiento"
            )
        limitations = data.get("limitations") or []
        if not isinstance(limitations, list) or len(limitations) > MAX_LIMITATIONS:
            raise ModelCardError(f"limitations debe ser una lista de hasta {MAX_LIMITATIONS}")
        model_version = data.get("model_version")
        if not isinstance(model_version, str) or not MODEL_VERSION.match(model_version):
            raise ModelCardError("model_version inválida (letras, números, '.', '-', '_')")
        height, width = data["input_size"]
        return cls(
            model_version=model_version,
            is_demo=is_demo,
            classes=classes,
            input_size=(int(height), int(width)),
            color_mode=data.get("color_mode", "rgb"),
            preprocessing=data["preprocessing"],
            files=dict(data.get("files", {})),
            preprocessing_version=version,
            calibration=_calibration(data.get("calibration")),
            description=_optional_text(data.get("description"), "description"),
            intended_use=_optional_text(data.get("intended_use"), "intended_use"),
            training=_training(data.get("training")),
            metrics=_metrics(data.get("metrics"), classes),
            limitations=tuple(_text(item, "limitations") for item in limitations),
            recommended_thresholds=_thresholds(data.get("recommended_thresholds")),
        )

    @classmethod
    def load(cls, path: Path) -> "ModelCard":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def calibrated(self) -> bool:
        return self.calibration.temperature != 1.0

    def public_view(self) -> dict:
        """Lo que se publica en "Acerca del modelo": SOLO lo que trae la ficha, sin huellas."""
        view: dict = {
            "model_version": self.model_version,
            "is_demo": self.is_demo,
            "classes": list(self.classes),
            "input_size": list(self.input_size),
            "calibrated": self.calibrated,
        }
        if self.calibrated:
            view["calibration"] = {
                "method": self.calibration.method,
                "temperature": self.calibration.temperature,
            }
        optional = {
            "description": self.description,
            "intended_use": self.intended_use,
            "training": self.training,
            "metrics": self.metrics,
            "limitations": list(self.limitations) or None,
        }
        view.update({k: v for k, v in optional.items() if v is not None})
        return view
