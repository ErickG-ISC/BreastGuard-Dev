"""Huella de paridad del modelo (backend/ml_tools/parity.py, ADR 0013).

- Rápida (CI, sin TensorFlow ni modelo): el conjunto sintético y el preprocesamiento dan
  EXACTAMENTE los mismos tensores que cuando se generó la huella. Si alguien cambia el
  redimensionado, el modo de color o la escala, esta prueba falla antes de llegar a producción.
- Lenta (con el modelo, BREASTGUARD_TEST_MODEL_DIR): LiteRT reproduce las probabilidades de la
  huella de esa versión del modelo.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from backend.app.ml.config import ModelCard
from backend.ml_tools.parity import N_IMAGES, image_sha256, synthetic_set, tensor_sha256

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FINGERPRINTS = sorted(FIXTURES.glob("parity_*.json"))


def _card(fp: dict) -> ModelCard:
    return ModelCard.from_dict({**fp, "files": {}})


def test_hay_al_menos_una_huella():
    assert FINGERPRINTS, "Falta tests/fixtures/parity_<version>.json (ml_tools/parity --write)"


def test_conjunto_sintetico_estable():
    images = synthetic_set()
    assert len(images) == N_IMAGES
    assert len({image_sha256(img) for _, img in images}) == N_IMAGES  # todas distintas


@pytest.mark.parametrize("path", FINGERPRINTS, ids=lambda p: p.stem)
def test_preprocesamiento_identico_a_la_huella(path):
    from backend.app.ml.runtime import to_model_input

    fp = json.loads(path.read_text(encoding="utf-8"))
    card = _card(fp)
    expected = {row["name"]: row for row in fp["images"]}
    for name, image in synthetic_set():
        row = expected[name]
        assert image_sha256(image) == row["image_sha256"], name
        assert tensor_sha256(to_model_input(image, card)) == row["input_sha256"], name


@pytest.mark.slow
def test_litert_reproduce_la_huella():
    model_dir = os.environ.get("BREASTGUARD_TEST_MODEL_DIR")
    if not model_dir or not (Path(model_dir) / "model_card.json").exists():
        pytest.skip("Sin modelo exportado (BREASTGUARD_TEST_MODEL_DIR)")
    from backend.app.ml.runtime import LiteRTPredictor

    card = ModelCard.load(Path(model_dir) / "model_card.json")
    path = FIXTURES / f"parity_{card.model_version}.json"
    if not path.exists():
        pytest.skip(f"Sin huella para {card.model_version}")
    fp = json.loads(path.read_text(encoding="utf-8"))
    predictor = LiteRTPredictor(Path(model_dir), card)
    expected = {row["name"]: row["litert_probabilities"] for row in fp["images"]}
    for name, image in synthetic_set():
        probs = predictor.predict(image).probabilities
        got = np.array([probs[c] for c in card.classes])
        assert np.allclose(got, expected[name], atol=1e-5), name
