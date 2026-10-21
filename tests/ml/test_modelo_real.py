"""Prueba LENTA con el modelo exportado (demostración o real). Se omite si no está disponible.

Uso: BREASTGUARD_TEST_MODEL_DIR=<carpeta con model_card.json> pytest -m slow tests/ml
"""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.app.ml.config import ModelCard
from backend.app.ml.heatmap import class_activation_map
from backend.app.ml.runtime import LiteRTPredictor, to_model_input

pytestmark = pytest.mark.slow

MODEL_DIR = os.environ.get("BREASTGUARD_TEST_MODEL_DIR")


@pytest.fixture(scope="module")
def model_dir() -> Path:
    if not MODEL_DIR or not (Path(MODEL_DIR) / "model_card.json").exists():
        pytest.skip("Sin modelo exportado (BREASTGUARD_TEST_MODEL_DIR)")
    return Path(MODEL_DIR)


@pytest.fixture(scope="module")
def predictor(model_dir) -> LiteRTPredictor:
    return LiteRTPredictor(model_dir, ModelCard.load(model_dir / "model_card.json"))


def sample() -> Image.Image:
    rng = np.random.default_rng(3)
    return Image.fromarray(rng.gamma(2.0, 30.0, (300, 400)).clip(0, 255).astype(np.uint8), "L")


def test_litert_da_probabilidades_y_activaciones(predictor):
    prediction = predictor.predict(sample())
    assert sum(prediction.probabilities.values()) == pytest.approx(1.0, abs=1e-4)
    assert set(prediction.probabilities) == set(predictor.card.classes)
    assert prediction.features.ndim == 3


def test_cam_numpy_igual_a_gradcam_de_tensorflow(predictor, model_dir):
    """Para GAP + Dense, Grad-CAM (gradiente de la logit) y CAM deben coincidir."""
    tf = pytest.importorskip("tensorflow")
    model = tf.keras.models.load_model(model_dir / "model.keras")
    if not (model_dir / "model.keras").exists():
        pytest.skip("Sin model.keras para comparar")
    image = sample()
    batch = to_model_input(image, predictor.card)
    dense = model.get_layer("predictions")
    features_layer = model.get_layer("top_activation")
    grad_model = tf.keras.Model(model.inputs, [features_layer.output, dense.input])
    prediction = predictor.predict(image)
    target = predictor.card.classes.index(prediction.predicted_class)
    with tf.GradientTape() as tape:
        features, pooled = grad_model(batch)
        logit = tf.matmul(pooled, dense.kernel)[:, target] + dense.bias[target]
    grads = tape.gradient(logit, features)
    weights = tf.reduce_mean(grads, axis=(1, 2))[0].numpy()
    gradcam = np.maximum((features[0].numpy() * weights).sum(axis=-1), 0)
    gradcam = gradcam / gradcam.max() if gradcam.max() > 0 else gradcam

    cam = class_activation_map(
        prediction.features, predictor.class_weights(prediction.predicted_class)
    )
    assert np.allclose(cam, gradcam, atol=1e-3)


def test_keras_y_tflite_coinciden(predictor, model_dir):
    tf = pytest.importorskip("tensorflow")
    model = tf.keras.models.load_model(model_dir / "model.keras")
    image = sample()
    keras_probs = model.predict(to_model_input(image, predictor.card), verbose=0)[0]
    tflite_probs = np.array(
        [predictor.predict(image).probabilities[c] for c in predictor.card.classes]
    )
    assert np.allclose(keras_probs, tflite_probs, atol=1e-4)
