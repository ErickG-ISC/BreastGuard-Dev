"""Ficha del modelo (`model_card.json`): única fuente de clases, tamaño y preprocesamiento."""

import json
from dataclasses import dataclass
from pathlib import Path

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
PREPROCESSING_MODES = ("raw_0_255", "scale_0_1", "scale_minus1_1")


class ModelCardError(ValueError):
    pass


@dataclass(frozen=True)
class ModelCard:
    model_version: str
    is_demo: bool
    classes: tuple[str, ...]  # canónicos, en el ORDEN de salida del modelo
    input_size: tuple[int, int]
    color_mode: str
    preprocessing: str
    files: dict[str, str]  # nombre -> sha256

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
        height, width = data["input_size"]
        return cls(
            model_version=str(data["model_version"]),
            is_demo=bool(data.get("is_demo", False)),
            classes=classes,
            input_size=(int(height), int(width)),
            color_mode=data.get("color_mode", "rgb"),
            preprocessing=data["preprocessing"],
            files=dict(data.get("files", {})),
        )

    @classmethod
    def load(cls, path: Path) -> "ModelCard":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
