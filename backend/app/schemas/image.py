import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ImageUploadOut(BaseModel):
    message: str
    image_id: uuid.UUID


class ImageOut(BaseModel):
    """Metadatos de una imagen (sin URL). Nunca incluye la ruta interna de Storage."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    image_type: str
    prediction: str | None
    confidence: float | None
    created_at: datetime


class ImageDetailOut(ImageOut):
    url: str
    url_expires_in: int
