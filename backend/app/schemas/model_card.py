"""Salida pública de "Acerca del modelo" (ADR 0014): solo lo que trae la ficha cargada."""

from pydantic import BaseModel


class CalibrationOut(BaseModel):
    method: str
    temperature: float


class ModelCardOut(BaseModel):
    status: str  # loaded | unavailable
    disclaimer: str
    mammography_warning: str
    model_version: str | None = None
    is_demo: bool | None = None
    classes: list[str] | None = None
    input_size: list[int] | None = None
    calibrated: bool | None = None
    calibration: CalibrationOut | None = None
    description: str | None = None
    intended_use: str | None = None
    training: dict[str, str | float | bool] | None = None
    metrics: dict | None = None
    limitations: list[str] | None = None
