"""Chequeos de entrada: rechazar lo que claramente no es una ecografía y marcar lo dudoso."""

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from backend.app.ml.runtime import Prediction
from backend.app.ml.settings import MLSettings


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str


def check_image(image: Image.Image, settings: MLSettings) -> list[QualityIssue]:
    """Problemas que impiden analizar la imagen (se responde 422 con el mensaje)."""
    issues: list[QualityIssue] = []
    if min(image.size) < settings.min_side_px:
        issues.append(
            QualityIssue(
                "too_small",
                f"La imagen es muy pequeña (mínimo {settings.min_side_px} px por lado).",
            )
        )
    hsv = np.asarray(image.convert("RGB").convert("HSV"), dtype=np.float32)
    if float(hsv[..., 1].mean()) / 255.0 > settings.max_mean_saturation:
        issues.append(
            QualityIssue(
                "color_image",
                "La imagen parece una foto a color; sube una ecografía (en escala de grises).",
            )
        )
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    if float(gray.std()) < settings.min_pixel_stddev:
        issues.append(
            QualityIssue("uniform", "La imagen es casi uniforme; no parece una ecografía.")
        )
    return issues


def normalized_entropy(probabilities: dict[str, float]) -> float:
    values = [p for p in probabilities.values() if p > 0]
    if len(probabilities) < 2:
        return 0.0
    entropy = -sum(p * math.log(p) for p in values)
    return entropy / math.log(len(probabilities))


def prediction_flags(prediction: Prediction, settings: MLSettings) -> list[str]:
    """Marcas que vuelven el resultado NO CONCLUYENTE (se recomienda consultar)."""
    flags = []
    if prediction.confidence < settings.confidence_min:
        flags.append("low_confidence")
    if normalized_entropy(prediction.probabilities) > settings.max_normalized_entropy:
        flags.append("high_uncertainty")
    return flags
