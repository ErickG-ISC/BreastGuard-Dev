"""Tarjeta del modelo v2 (ADR 0014): calibración, versión del preprocesamiento y vista pública."""

import numpy as np
import pytest
from PIL import Image

from backend.app.ml.config import ModelCard, ModelCardError
from backend.app.ml.preprocess import PREPROCESSING_VERSION
from backend.app.ml.runtime import FakePredictor
from backend.app.ml.service import run_analysis
from backend.app.ml.settings import MLSettings

BASE = {
    "model_version": "real-1",
    "preprocessing_version": PREPROCESSING_VERSION,
    "classes": ["normal", "benign", "malignant"],
    "input_size": [224, 224],
    "preprocessing": "raw_0_255",
    "files": {"model.tflite": "a" * 64, "head.npz": "b" * 64},
}


def card(**extra) -> ModelCard:
    return ModelCard.from_dict({**BASE, **extra})


def ultrasound() -> Image.Image:
    rng = np.random.default_rng(1)
    return Image.fromarray(rng.gamma(2.0, 30.0, (300, 400)).clip(0, 255).astype(np.uint8), "L")


class TestCalibracion:
    def test_sin_calibracion_no_cambia_nada(self):
        c = card()
        probs = np.array([0.7, 0.2, 0.1])
        assert c.calibration.apply(probs) is probs
        assert not c.calibrated

    def test_temperatura_mayor_que_uno_reparte_y_conserva_la_clase(self):
        c = card(calibration={"method": "temperature", "temperature": 2.0})
        out = c.calibration.apply(np.array([0.7, 0.2, 0.1]))
        assert out.sum() == pytest.approx(1.0)
        assert int(np.argmax(out)) == 0
        assert out[0] < 0.7  # menos confianza
        # softmax(log p / T) con T = 2 es proporcional a sqrt(p)
        expected = np.sqrt([0.7, 0.2, 0.1]) / np.sqrt([0.7, 0.2, 0.1]).sum()
        assert np.allclose(out, expected)

    def test_temperatura_menor_que_uno_concentra(self):
        c = card(calibration={"method": "temperature", "temperature": 0.5})
        assert c.calibration.apply(np.array([0.7, 0.2, 0.1]))[0] > 0.7

    def test_probabilidad_cero_no_rompe(self):
        c = card(calibration={"method": "temperature", "temperature": 1.5})
        out = c.calibration.apply(np.array([1.0, 0.0, 0.0]))
        assert np.isfinite(out).all() and out.sum() == pytest.approx(1.0)

    def test_el_analisis_usa_la_confianza_calibrada(self):
        """La confianza del reporte y los umbrales se aplican a la probabilidad CALIBRADA."""
        raw = {"normal": 0.9, "benigno": 0.07, "maligno": 0.03}
        plain = run_analysis(ultrasound(), FakePredictor(card(), raw), MLSettings())
        calibrated_card = card(calibration={"method": "temperature", "temperature": 3.0})
        hot = run_analysis(ultrasound(), FakePredictor(calibrated_card, raw), MLSettings())
        assert plain.confidence == pytest.approx(0.9)
        assert hot.confidence < 0.6  # con T = 3 la confianza cae por debajo del mínimo
        assert hot.status == "inconclusive"
        assert sum(hot.probabilities.values()) == pytest.approx(1.0)


class TestValidacion:
    @pytest.mark.parametrize(
        "calibration",
        [
            {"method": "temperature", "temperature": 0},
            {"method": "temperature", "temperature": 100},
            {"method": "temperature", "temperature": "2"},
            {"method": "temperature", "temperature": float("nan")},
            {"method": "platt", "a": 1},
            "temperature",
        ],
    )
    def test_calibracion_invalida_no_carga(self, calibration):
        with pytest.raises(ModelCardError):
            card(calibration=calibration)

    def test_modelo_real_sin_version_de_preprocesamiento_no_carga(self):
        data = {k: v for k, v in BASE.items() if k != "preprocessing_version"}
        with pytest.raises(ModelCardError, match="preprocessing_version"):
            ModelCard.from_dict(data)

    def test_demo_sin_version_si_carga(self):
        data = {k: v for k, v in BASE.items() if k != "preprocessing_version"}
        assert ModelCard.from_dict({**data, "is_demo": True}).preprocessing_version is None

    @pytest.mark.parametrize("version", [PREPROCESSING_VERSION + 1, 0, True, "1"])
    def test_otra_version_de_preprocesamiento_no_carga(self, version):
        with pytest.raises(ModelCardError):
            card(preprocessing_version=version)

    @pytest.mark.parametrize(
        "metrics",
        [
            {"confusion_matrix": [[1, 2], [3, 4]]},
            {"confusion_matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9.5]]},
            {"confusion_matrix": [[1, 2, 3], [4, 5, 6], [7, 8, -1]]},
            {"per_class": {"tumor": {"sensitivity": 0.9}}},
            {"sensitivity_malignant": "alta"},
            {"auc": float("inf")},
            ["no es objeto"],
        ],
    )
    def test_metricas_invalidas_no_cargan(self, metrics):
        with pytest.raises(ModelCardError):
            card(metrics=metrics)

    @pytest.mark.parametrize(
        "extra",
        [
            {"limitations": "una sola cadena"},
            {"limitations": ["ok", 3]},
            {"limitations": ["x"] * 31},
            {"description": "x" * 2001},
            {"intended_use": ""},
            {"training": {"dataset": ["lista"]}},
            {"recommended_thresholds": {"confidence_min": "0.6"}},
            {"model_version": "../otro"},
            {"model_version": "a/b"},
            {"model_version": ""},
            {"model_version": 3},
            {"training": {"Ruta del bucket": "x"}},
            {"training": {f"k{i}": i for i in range(31)}},
            {"metrics": {"auc mal": 0.9}},
        ],
    )
    def test_campos_informativos_invalidos_no_cargan(self, extra):
        with pytest.raises(ModelCardError):
            card(**extra)


class TestVistaPublica:
    def test_solo_lo_que_trae_la_ficha_y_sin_huellas(self):
        view = card().public_view()
        assert view == {
            "model_version": "real-1",
            "is_demo": False,
            "classes": ["normal", "benigno", "maligno"],
            "input_size": [224, 224],
            "calibrated": False,
        }

    def test_ficha_completa(self):
        view = card(
            description="EfficientNet-B0 entrenado con BUSI",
            intended_use="Apoyo en ecografía mamaria",
            training={"dataset": "BUSI", "images": 780, "split_by_patient": True},
            metrics={
                "confusion_matrix": [[30, 2, 1], [3, 40, 4], [1, 5, 20]],
                "per_class": {"malignant": {"sensitivity": 0.77, "specificity": 0.94}},
                "ece_before": 0.12,
                "ece_after": 0.04,
                "test_set": "20 % por paciente",
            },
            limitations=["No validado para mastografía"],
            calibration={"method": "temperature", "temperature": 1.4},
            recommended_thresholds={"confidence_min": 0.55},
        ).public_view()
        assert view["metrics"]["per_class"] == {
            "maligno": {"sensitivity": 0.77, "specificity": 0.94}
        }
        assert view["calibration"] == {"method": "temperature", "temperature": 1.4}
        assert view["training"]["images"] == 780
        # Los umbrales recomendados son solo para el equipo: no se publican ni se aplican
        assert "recommended_thresholds" not in view
        assert "files" not in view and "a" * 64 not in str(view)
