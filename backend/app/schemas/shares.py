"""Paquete compartido con la médica (CU-07). Entrada de la paciente y lo que ella ve después."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

MAX_ANALYSES = 10
ExpiryHours = Literal[24, 72, 168]


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_ANALYSES)
    include_diary: bool = False
    include_questionnaire: bool = False
    # Opcionales y apagados por defecto: notas libres y datos que identifican
    include_notes: bool = False
    include_identity: bool = False
    expires_in_hours: ExpiryHours = 24
    recipient_email: EmailStr | None = None
    consent_accepted: Literal[True]
    consent_version: str = Field(min_length=1, max_length=40)

    @field_validator("analysis_ids")
    @classmethod
    def unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Hay análisis repetidos")
        return value

    @field_validator("recipient_email")
    @classmethod
    def lower_email(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @model_validator(mode="after")
    def something_to_share(self):
        if not (self.analysis_ids or self.include_diary or self.include_questionnaire):
            raise ValueError("Elige al menos qué compartir")
        if self.include_notes and not self.include_diary:
            raise ValueError("Las notas solo se comparten junto con el diario")
        return self


class ShareCreated(BaseModel):
    """El código se muestra UNA vez: el servidor no lo guarda y no puede volver a darlo."""

    id: uuid.UUID
    code: str
    link: str
    expires_at: datetime


class ShareEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    occurred_at: datetime
    institution_name: str | None
    doctor_name: str | None


class ShareOut(BaseModel):
    id: uuid.UUID
    status: Literal["activo", "importando", "importado", "revocado", "caducado"]
    created_at: datetime
    expires_at: datetime
    sections: dict[str, bool]
    analyses_count: int
    recipient_email: str | None
    events: list[ShareEventOut]


class ShareList(BaseModel):
    items: list[ShareOut]


class ShareConsentOut(BaseModel):
    version: str
    text: str
    sha256: str


class CleanupOut(BaseModel):
    expired: int
    purged: int
    failed: int


class ShareImport(BaseModel):
    """El código lo escribe o lo trae el enlace (fragmento #c=); nunca va en la URL de la API."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)


class ShareImported(BaseModel):
    patient_id: uuid.UUID
    analyses: int
    symptoms: int
    already_imported: bool


class InboxNoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    created_at: datetime
    read_at: datetime | None
