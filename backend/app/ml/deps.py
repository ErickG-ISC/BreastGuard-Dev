"""Dependencia del servicio de inferencia (cargado una vez en el lifespan)."""

from typing import Annotated

from fastapi import Depends, Request

from backend.app.ml.service import InferenceService


def get_inference(request: Request) -> InferenceService:
    return request.app.state.inference


Inference = Annotated[InferenceService, Depends(get_inference)]
