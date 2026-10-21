"""Mapa de calor del análisis, detrás de `generate_heatmap(image, model)` para poder cambiarlo.

Para cabezas GlobalAveragePooling -> Dense (EfficientNet), el Grad-CAM de la puntuación de una
clase es EXACTAMENTE el CAM: el gradiente de la logit respecto a cada activación es
w[k, c] / (H·W), así que los pesos de Grad-CAM son proporcionales a los pesos del Dense.
Se calcula en numpy con las activaciones que devuelve el predictor: sin TensorFlow.
"""

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from backend.app.ml.runtime import Prediction, Predictor

OVERLAY_ALPHA = 0.45


@dataclass(frozen=True)
class Heatmap:
    cam: np.ndarray  # (h, w) normalizado 0–1, a la resolución de las activaciones
    overlay_png: bytes  # imagen original con el mapa superpuesto


def class_activation_map(features: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """CAM = ReLU(Σ_k w_k · A_k), normalizado a 0–1."""
    cam = np.maximum(np.tensordot(features, weights, axes=([2], [0])), 0.0)
    peak = float(cam.max())
    return cam / peak if peak > 0 else cam


def _colormap(values: np.ndarray) -> np.ndarray:
    """Mapa de color tipo 'jet' (azul -> verde -> amarillo -> rojo) sin matplotlib."""
    v = np.clip(values, 0.0, 1.0)
    red = np.clip(1.5 - np.abs(4 * v - 3), 0, 1)
    green = np.clip(1.5 - np.abs(4 * v - 2), 0, 1)
    blue = np.clip(1.5 - np.abs(4 * v - 1), 0, 1)
    return (np.stack([red, green, blue], axis=-1) * 255).astype(np.uint8)


def overlay(image: Image.Image, cam: np.ndarray, alpha: float = OVERLAY_ALPHA) -> bytes:
    base = image.convert("RGB")
    heat = Image.fromarray((cam * 255).astype(np.uint8), mode="L").resize(
        base.size, Image.Resampling.BILINEAR
    )
    colored = Image.fromarray(_colormap(np.asarray(heat, dtype=np.float32) / 255.0), mode="RGB")
    blended = Image.blend(base, colored, alpha)
    buffer = io.BytesIO()
    blended.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def generate_heatmap(
    image: Image.Image,
    model: Predictor,
    prediction: Prediction | None = None,
    class_name: str | None = None,
) -> Heatmap:
    """Mapa de calor de `class_name` (por defecto, la clase predicha) sobre la imagen original."""
    prediction = prediction or model.predict(image)
    target = class_name or prediction.predicted_class
    cam = class_activation_map(prediction.features, model.class_weights(target))
    return Heatmap(cam=cam, overlay_png=overlay(image, cam))
