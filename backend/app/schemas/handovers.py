"""Traspaso de pacientes entre médicas (0014). Solo ids, nombres del personal y fechas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HandoverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_user_id: uuid.UUID


class HandoverOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    from_doctor_id: uuid.UUID
    from_name: str
    to_doctor_id: uuid.UUID
    to_name: str
    status: Literal["pending", "accepted", "cancelled"]
    created_at: datetime
    accepted_at: datetime | None
    cancelled_at: datetime | None
    # Cuántas fichas pasaron al aceptarlo (un conteo; nunca cuáles)
    patients_moved: int | None


class HandoverList(BaseModel):
    items: list[HandoverOut]


class PendingHandoverOut(BaseModel):
    """Lo que ve la médica de destino: de quién vienen y desde cuándo."""

    id: uuid.UUID
    from_name: str
    created_at: datetime


class HandoverAccepted(BaseModel):
    patients_moved: int
