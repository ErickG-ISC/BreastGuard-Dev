"""Herramientas del modelo nuevo (ADR 0014): efecto de umbrales y validación previa a subirlo."""

import numpy as np
import pytest

from backend.app.ml.settings import MLSettings
from backend.app.services import cases
from backend.ml_tools import threshold_effect as te

CLASSES = ["normal", "benigno", "maligno"]


def test_sospechoso_es_la_misma_regla_que_el_panel(monkeypatch):
    """La herramienta y el panel de la médica deben decir lo mismo con los umbrales vigentes."""
    rng = np.random.default_rng(0)
    for _ in range(200):
        raw = rng.dirichlet([1, 1, 1])
        result = te.evaluate(CLASSES, raw, 1.0, MLSettings())
        from backend.app.ml.quality import prediction_flags
        from backend.app.ml.runtime import Prediction

        prediction = Prediction(
            dict(zip(CLASSES, map(float, raw), strict=True)), np.zeros((1, 1, 1))
        )
        flags = prediction_flags(prediction, MLSettings())
        assert result["suspicious"] == cases.is_suspicious(prediction.predicted_class, flags)


def test_sin_cambios_no_cambia_nada():
    probs = [np.array(p) for p in ([0.9, 0.05, 0.05], [0.2, 0.3, 0.5], [0.4, 0.35, 0.25])]
    out = te.compare(CLASSES, probs, [None] * 3, (1.0, MLSettings()), (1.0, MLSettings()))
    assert out["changed_level"] == 0 and out["transitions"] == {}
    assert out["entered_suspicious"] == out["left_suspicious"] == 0


def test_bajar_el_umbral_de_atencion_suma_sospechosos_y_sensibilidad(tmp_path):
    csv = tmp_path / "val.csv"
    csv.write_text(
        "label,normal,benign,malignant\n"
        "maligno,0.70,0.10,0.20\n"  # maligno real que hoy no se marca (0.20 < 0.25)
        "maligno,0.10,0.20,0.70\n"
        "normal,0.95,0.03,0.02\n",
        encoding="utf-8",
    )
    classes, probs, labels = te.read_predictions(csv)
    current = MLSettings()
    proposed = MLSettings(malignant_attention_probability=0.15)
    out = te.compare(classes, probs, labels, (1.0, current), (1.0, proposed))
    assert out["current"]["malignant_sensitivity"] == 0.5
    assert out["proposed"]["malignant_sensitivity"] == 1.0
    assert out["entered_suspicious"] == 1
    assert out["changed_level"] == 1


def test_umbral_desconocido_se_rechaza():
    with pytest.raises(SystemExit):
        te.parse_overrides(["suspicious_classes=0.1"])


def test_temperatura_cambia_niveles():
    probs = [np.array([0.66, 0.2, 0.14])]
    out = te.compare(CLASSES, probs, [None], (1.0, MLSettings()), (3.0, MLSettings()))
    assert out["transitions"]  # con T = 3 baja la confianza y el nivel cambia
