"""Ficha pública del modelo ("Acerca del modelo", ADR 0014). Sin sesión ni datos de tenant.

Solo publica campos de la ficha CARGADA, por lista blanca (`ModelCard.public_view`): nunca
huellas de archivos, rutas del bucket ni umbrales internos. Si un dato no está en la ficha, no
aparece: la página no inventa métricas.
"""

from fastapi import APIRouter

from backend.app.ml.deps import Inference
from backend.app.ml.profiles import PROTOTYPE_WARNING
from backend.app.ml.report import DISCLAIMER
from backend.app.schemas.model_card import ModelCardOut

router = APIRouter()


@router.get("/model/card", response_model=ModelCardOut, response_model_exclude_none=True)
def get_model_card(inference: Inference) -> ModelCardOut:
    common = {"disclaimer": DISCLAIMER, "mammography_warning": PROTOTYPE_WARNING}
    if not inference.available:
        return ModelCardOut(status="unavailable", **common)
    return ModelCardOut(status="loaded", **common, **inference.predictor.card.public_view())
