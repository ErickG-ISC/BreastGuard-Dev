import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnalysisOut(BaseModel):
    """Resultado de un análisis. Nunca incluye rutas internas de Storage."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    predicted_class: str
    probabilities: dict[str, float]
    confidence: float
    model_version: str
    quality_flags: list[str]
    report: dict
    created_at: datetime


class AnalysisDetailOut(AnalysisOut):
    image_url: str
    heatmap_url: str
    url_expires_in: int


class AnalysisPage(BaseModel):
    items: list[AnalysisOut]
    total: int
    limit: int
    offset: int
