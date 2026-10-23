import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NoticedChange = Literal["si", "no", "no_segura"]


class GuideStep(BaseModel):
    id: str
    title: str
    illustration: str
    instructions: list[str]
    look_for: list[str]


class GuideOut(BaseModel):
    version: str
    status: str
    status_note: str
    title: str
    intro: str
    steps: list[GuideStep]
    closing: str
    disclaimer: str


class SelfExamFinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    noticed_change: NoticedChange
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def blank_note_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Postgres no admite el carácter nulo en texto: 422 en lugar de un 500
        if "\x00" in value:
            raise ValueError("La nota contiene caracteres no válidos")
        value = value.strip()
        return value or None


class SelfExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_version: str
    started_at: datetime
    finished_at: datetime | None
    noticed_change: NoticedChange | None
    note: str | None


class SelfExamPage(BaseModel):
    items: list[SelfExamOut]
    total: int
    limit: int
    offset: int
