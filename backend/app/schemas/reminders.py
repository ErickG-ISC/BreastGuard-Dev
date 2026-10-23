import uuid
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.services.reminder_schedule import ScheduleError, zone

Kind = Literal["self_exam", "repeat_analysis"]
Frequency = Literal["first_sunday", "every_n_days", "every_n_months"]
Channel = Literal["in_app", "email"]
INTERVAL_LIMITS = {"every_n_days": (1, 90), "every_n_months": (1, 24)}


class ReminderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: Frequency
    interval_n: int | None = None
    local_time: time
    timezone: str = Field(max_length=64)
    channels: list[Channel] = Field(min_length=1, max_length=2)
    discreet: bool = True
    active: bool = True

    @field_validator("local_time")
    @classmethod
    def quarter_hours(cls, value: time) -> time:
        # El despachador corre cada 15 minutos
        if value.minute % 15 or value.second or value.microsecond or value.tzinfo:
            raise ValueError("La hora debe ser en punto, y cuarto, y media o menos cuarto")
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            zone(value)
        except ScheduleError:
            raise ValueError("Zona horaria desconocida") from None
        return value

    @field_validator("channels")
    @classmethod
    def unique_channels(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Hay canales repetidos")
        return value

    @model_validator(mode="after")
    def interval_matches_frequency(self):
        limits = INTERVAL_LIMITS.get(self.frequency)
        if limits is None:
            if self.interval_n is not None:
                raise ValueError("El primer domingo del mes no lleva intervalo")
        elif self.interval_n is None or not limits[0] <= self.interval_n <= limits[1]:
            raise ValueError(f"El intervalo debe estar entre {limits[0]} y {limits[1]}")
        return self


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Kind
    frequency: Frequency
    interval_n: int | None
    local_time: time
    timezone: str
    channels: list[Channel]
    discreet: bool
    active: bool
    next_run_at: datetime
    last_run_at: datetime | None


class NoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: Kind
    due_at: datetime
    read_at: datetime | None
    created_at: datetime


class UnsubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=2000)


class DispatchOut(BaseModel):
    claimed: int
    emailed: int
    failed: int
