import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Side = Literal["izquierdo", "derecho", "ambos"]
Zone = Literal[
    "superior_externo",
    "superior_interno",
    "inferior_externo",
    "inferior_interno",
    "areola_pezon",
    "axila",
    "otra",
]
Symptom = Literal[
    "bulto",
    "dolor",
    "sensibilidad",
    "secrecion",
    "cambio_piel",
    "cambio_pezon",
    "enrojecimiento",
    "otro",
]
EARLIEST_DATE = date(2000, 1, 1)


def _check_date(value: date | None) -> date | None:
    # Un día de margen: la fecha es local de la paciente y el servidor está en UTC
    if value is not None and not (EARLIEST_DATE <= value <= date.today() + timedelta(days=1)):
        raise ValueError("La fecha no puede ser futura")
    return value


def _clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    # Postgres no admite el carácter nulo en texto: 422 en lugar de un 500
    if "\x00" in value:
        raise ValueError("La nota contiene caracteres no válidos")
    value = value.strip()
    return value or None


def _unique(values: list[str] | None) -> list[str] | None:
    if values is not None and len(set(values)) != len(values):
        raise ValueError("Hay síntomas repetidos")
    return values


class SymptomEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_date: date
    side: Side
    zone: Zone
    symptoms: list[Symptom] = Field(min_length=1, max_length=8)
    intensity: int = Field(ge=0, le=10)
    note: str | None = Field(default=None, max_length=2000)
    self_exam_id: uuid.UUID | None = None
    cycle_day: int | None = Field(default=None, ge=1, le=60)
    in_period: bool | None = None

    _date = field_validator("entry_date")(_check_date)
    _note = field_validator("note")(_clean_note)
    _symptoms = field_validator("symptoms")(_unique)


class SymptomEntryUpdate(BaseModel):
    """Cambios parciales: solo los campos enviados se modifican (null borra los opcionales)."""

    model_config = ConfigDict(extra="forbid")

    entry_date: date | None = None
    side: Side | None = None
    zone: Zone | None = None
    symptoms: list[Symptom] | None = Field(default=None, min_length=1, max_length=8)
    intensity: int | None = Field(default=None, ge=0, le=10)
    note: str | None = Field(default=None, max_length=2000)
    self_exam_id: uuid.UUID | None = None
    cycle_day: int | None = Field(default=None, ge=1, le=60)
    in_period: bool | None = None

    _date = field_validator("entry_date")(_check_date)
    _note = field_validator("note")(_clean_note)
    _symptoms = field_validator("symptoms")(_unique)

    @model_validator(mode="after")
    def required_fields_not_null(self):
        for name in ("entry_date", "side", "zone", "symptoms", "intensity"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} no puede ser nulo")
        return self


class SymptomEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_date: date
    side: Side
    zone: Zone
    symptoms: list[Symptom]
    intensity: int
    note: str | None
    self_exam_id: uuid.UUID | None
    cycle_day: int | None
    in_period: bool | None
    created_at: datetime
    updated_at: datetime | None


class SymptomEntryPage(BaseModel):
    items: list[SymptomEntryOut]
    total: int
    limit: int
    offset: int
