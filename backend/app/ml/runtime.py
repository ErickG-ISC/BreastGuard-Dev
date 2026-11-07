"""Predictores: LiteRT en producción (sin TensorFlow) y un doble determinista para pruebas.

Todo predictor devuelve probabilidades por clase canónica y las activaciones de la última capa
convolucional, que `heatmap.generate_heatmap` usa para el mapa de calor.
"""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from backend.app.ml.config import ModelCard
from backend.app.ml.preprocess import to_tensor


@dataclass(frozen=True)
class Prediction:
    probabilities: dict[str, float]  # clase canónica -> probabilidad
    features: np.ndarray  # (h, w, k) activaciones de la última capa convolucional

    @property
    def predicted_class(self) -> str:
        return max(self.probabilities, key=self.probabilities.get)

    @property
    def confidence(self) -> float:
        return self.probabilities[self.predicted_class]


class Predictor(Protocol):
    card: ModelCard

    def predict(self, image: Image.Image) -> Prediction: ...

    def class_weights(self, class_name: str) -> np.ndarray:
        """Pesos (k,) de la capa densa final para la clase: base del mapa CAM."""
        ...


def to_model_input(image: Image.Image, card: ModelCard) -> np.ndarray:
    """Imagen PIL -> tensor (1, H, W, C) float32 según la ficha (ver ml/preprocess.py)."""
    return to_tensor(image, card.input_size, card.color_mode, card.preprocessing)


def _probabilities(card: ModelCard, raw) -> dict[str, float]:
    """Salida del modelo -> probabilidades CALIBRADAS por clase canónica (ADR 0014)."""
    calibrated = card.calibration.apply(np.asarray(raw, dtype=float))
    return {name: float(p) for name, p in zip(card.classes, calibrated, strict=True)}


class LiteRTPredictor:
    """Modelo TFLite con dos salidas (probabilidades y activaciones) + pesos del Dense."""

    def __init__(self, model_dir: Path, card: ModelCard) -> None:
        from ai_edge_litert.interpreter import Interpreter

        self.card = card
        self._interpreter = Interpreter(model_path=str(model_dir / "model.tflite"), num_threads=1)
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]["index"]
        outputs = self._interpreter.get_output_details()
        n_classes = len(card.classes)
        # El orden de las salidas no está garantizado: se identifican por forma
        self._probs_index = next(o["index"] for o in outputs if len(o["shape"]) == 2)
        self._features_index = next(o["index"] for o in outputs if len(o["shape"]) == 4)
        probs_shape = next(o["shape"] for o in outputs if o["index"] == self._probs_index)
        if int(probs_shape[-1]) != n_classes:
            raise ValueError("El número de clases del modelo no coincide con la ficha")
        self._lock = threading.Lock()
        head = np.load(model_dir / "head.npz", allow_pickle=False)
        self._kernel = head["kernel"].astype(np.float32)  # (k, clases)

    def predict(self, image: Image.Image) -> Prediction:
        tensor = to_model_input(image, self.card)
        # El intérprete no es seguro entre hilos: aunque se suba MAX_CONCURRENT_INFERENCES, el
        # lock evita que una paciente reciba la salida de otra
        with self._lock:
            self._interpreter.set_tensor(self._input, tensor)
            self._interpreter.invoke()
            probs = self._interpreter.get_tensor(self._probs_index)[0].astype(float).copy()
            features = self._interpreter.get_tensor(self._features_index)[0].astype(np.float32)
        return Prediction(probabilities=_probabilities(self.card, probs), features=features)

    def class_weights(self, class_name: str) -> np.ndarray:
        return self._kernel[:, self.card.classes.index(class_name)]


class FakePredictor:
    """Doble determinista para pruebas: no carga ningún modelo."""

    def __init__(self, card: ModelCard, probabilities: dict[str, float] | None = None) -> None:
        self.card = card
        self.probabilities = probabilities
        rng = np.random.default_rng(7)
        self._features = rng.random((7, 7, 8), dtype=np.float32)
        self._kernel = rng.normal(size=(8, len(card.classes))).astype(np.float32)
        self.calls = 0

    def predict(self, image: Image.Image) -> Prediction:
        self.calls += 1
        to_model_input(image, self.card)  # ejercita el preprocesamiento real
        probs = self.probabilities or {
            name: 1.0 / len(self.card.classes) for name in self.card.classes
        }
        if not self.card.calibrated:
            return Prediction(probabilities=dict(probs), features=self._features)
        raw = [probs[name] for name in self.card.classes]
        return Prediction(probabilities=_probabilities(self.card, raw), features=self._features)

    def class_weights(self, class_name: str) -> np.ndarray:
        return self._kernel[:, self.card.classes.index(class_name)]
