"""GET /model/card (público) y versiones: un análisis viejo no se recalcula con otro modelo."""

from backend.app.main import app
from backend.app.ml.config import ModelCard
from backend.app.ml.deps import get_inference
from backend.app.ml.runtime import FakePredictor
from backend.app.ml.service import InferenceService
from backend.app.ml.settings import MLSettings
from tests.api.test_analyses import upload
from tests.conftest import DEMO_CARD
from tests.helpers import auth_headers

URL = "/api/v1/model/card"


def test_ficha_publica_sin_sesion(client):
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "loaded"
    assert body["model_version"] == "fake-3c-1"
    assert body["is_demo"] is True
    assert body["disclaimer"].startswith("Herramienta de apoyo")
    assert "mastografías" in body["mammography_warning"]
    # Solo lo que trae la ficha: la de prueba no tiene métricas
    assert "metrics" not in body and "training" not in body and "files" not in body


def test_sin_modelo_dice_no_disponible(client):
    app.dependency_overrides[get_inference] = lambda: InferenceService(None, MLSettings())
    body = client.get(URL).json()
    assert body["status"] == "unavailable"
    assert "model_version" not in body
    assert body["mammography_warning"]


def test_analisis_viejo_conserva_su_version_y_su_reporte(client, user_factory, b2c_tenant):
    ana = user_factory(b2c_tenant, role="patient")
    created = upload(client, ana).json()

    # Se "despliega" otro modelo, calibrado y con otras probabilidades
    new_card = ModelCard.from_dict(
        {
            **DEMO_CARD,
            "model_version": "fake-3c-2",
            "calibration": {"method": "temperature", "temperature": 2.5},
        }
    )
    new = FakePredictor(new_card, {"normal": 0.1, "benigno": 0.2, "maligno": 0.7})
    app.dependency_overrides[get_inference] = lambda: InferenceService(new, MLSettings())

    old = client.get(f"/api/v1/analyses/{created['id']}", headers=auth_headers(ana)).json()
    assert old["model_version"] == "fake-3c-1"
    for key in ("predicted_class", "probabilities", "confidence", "report", "status"):
        assert old[key] == created[key], key
    assert new.calls == 0  # leer no vuelve a pasar la imagen por el modelo

    fresh = upload(client, ana).json()
    assert fresh["model_version"] == "fake-3c-2"
    assert client.get(URL).json()["calibrated"] is True


def _serve(card_data: dict):
    card = ModelCard.from_dict(card_data)
    app.dependency_overrides[get_inference] = lambda: InferenceService(
        FakePredictor(card), MLSettings()
    )


def test_ficha_rica_publica_solo_la_lista_blanca(client):
    _serve(
        {
            **DEMO_CARD,
            "is_demo": False,
            "preprocessing_version": 1,
            "files": {"model.tflite": "a" * 64, "head.npz": "b" * 64},
            "training": {"dataset": "BUSI", "images": 780},
            "metrics": {"auc": 0.9, "confusion_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
            "limitations": ["No validado para mastografía"],
            "recommended_thresholds": {"confidence_min": 0.5},
            "calibration": {"method": "temperature", "temperature": 1.3},
        }
    )
    body = client.get(URL).json()
    assert body["metrics"]["auc"] == 0.9 and body["training"]["dataset"] == "BUSI"
    assert body["calibration"]["temperature"] == 1.3
    assert "files" not in body and "recommended_thresholds" not in body
    assert "a" * 64 not in str(body)
