"""Panel (CU-11) y caso (CU-08) de la médica. Nunca se devuelve el modelo ORM."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PanelFilter = Literal["todas", "pendientes", "sospechosos", "revisadas"]
CaseStatus = Literal["pendiente", "en_revision", "revisado"]


class PatientSearch(BaseModel):
    """Por POST: el nombre buscado nunca va en la URL ni en los logs de acceso."""

    model_config = ConfigDict(extra="forbid")

    filter: PanelFilter = "todas"
    q: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=100_000)

    @field_validator("q")
    @classmethod
    def no_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Texto no válido")
        return value


class LastAnalysisOut(BaseModel):
    created_at: datetime
    predicted_class: str
    confidence: float
    inconclusive: bool
    suspicious: bool


class PanelRow(BaseModel):
    id: uuid.UUID
    display_name: str
    age_years: int | None
    origin: Literal["importado", "creado"]
    status: CaseStatus
    created_at: datetime
    last_analysis: LastAnalysisOut | None
    # Traspaso pendiente HACIA ella (aún de otra médica) o DESDE ella (aún suya)
    handover_from: str | None
    handover_to: str | None


class PanelPage(BaseModel):
    items: list[PanelRow]
    total: int
    limit: int
    offset: int


class PanelSummary(BaseModel):
    pending_review: int
    suspicious: int
    active: int


BiRads = Literal["0", "1", "2", "3", "4", "4A", "4B", "4C", "5", "6"]


class ReviewIn(BaseModel):
    """Categoría BI-RADS y recomendación que asigna LA MÉDICA (el modelo nunca sugiere BI-RADS)."""

    model_config = ConfigDict(extra="forbid")

    birads: BiRads
    recommendation: str | None = Field(default=None, max_length=2000)

    @field_validator("recommendation")
    @classmethod
    def clean(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Texto no válido")
        return value.strip() or None if value is not None else None


class ReviewOut(BaseModel):
    birads: str | None
    recommendation: str | None
    reviewed_by_name: str
    mine: bool
    updated_at: datetime


class NewPatientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    age_years: int | None = Field(default=None, ge=0, le=120)

    @field_validator("display_name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("El nombre no puede estar vacío")
        return value


class CreatedOut(BaseModel):
    id: uuid.UUID


class CaseAnalysisOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    status: str
    predicted_class: str
    probabilities: dict[str, float]
    confidence: float
    model_version: str
    quality_flags: list[str]
    report: dict
    profile: str
    suspicious: bool
    image_url: str
    heatmap_url: str
    # Lista blanca técnica del DICOM (vista, lateralidad, espaciado...); nunca datos personales
    dicom_meta: dict | None
    prototype_warning: str | None
    review: ReviewOut | None


class CaseSelfExamOut(BaseModel):
    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    noticed_change: str | None
    note: str | None


class CaseSymptomOut(BaseModel):
    id: uuid.UUID
    entry_date: date
    side: str
    zone: str
    symptoms: list[str]
    intensity: int
    note: str | None
    self_exam_id: uuid.UUID | None
    cycle_day: int | None
    in_period: bool | None


class CaseQuestionnaireOut(BaseModel):
    version: str
    answers: dict
    risk_factors: list
    summary_level: str
    created_at: datetime


class CaseNoteOut(BaseModel):
    id: uuid.UUID
    body: str
    author_id: uuid.UUID
    author_name: str
    mine: bool
    created_at: datetime
    updated_at: datetime | None


class CaseOut(BaseModel):
    id: uuid.UUID
    display_name: str
    age_years: int | None
    age_recorded_on: date | None
    origin: Literal["importado", "creado"]
    status: CaseStatus
    created_at: datetime
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    handover_from: str | None
    handover_to: str | None
    analyses: list[CaseAnalysisOut]
    self_exams: list[CaseSelfExamOut]
    symptoms: list[CaseSymptomOut]
    questionnaire: CaseQuestionnaireOut | None
    notes: list[CaseNoteOut]
    signed_url_ttl: int


class CaseStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CaseStatus


class CaseNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("La nota no puede estar vacía")
        return value
