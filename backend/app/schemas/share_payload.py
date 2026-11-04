"""Contenido descifrado de un paquete (CU-08): se valida ANTES de copiar nada.

Lo escribió el servidor al crear el paquete, pero la importación no confía en él: tipos
cerrados, nombres de objeto con forma fija (nunca rutas) y límites de tamaño y de conteo. Lo que
no cumpla se rechaza entero y no se sube ni se escribe nada.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.shares import MAX_ANALYSES
from backend.app.schemas.symptoms import Side, Symptom, Zone

# Nombre dentro de transfer/{uuid}/: el servidor lo genera como {uuid4().hex}.bin
ObjectName = Field(pattern=r"^[0-9a-f]{32}\.bin$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayloadPatient(_Strict):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    age_years: int | None = Field(default=None, ge=0, le=120)
    age_recorded_on: date | None = None


class PayloadAnalysis(_Strict):
    created_at: datetime | None = None
    status: Literal["completed", "inconclusive"]
    predicted_class: Literal["normal", "benigno", "maligno"]
    probabilities: dict[Literal["normal", "benigno", "maligno"], float] = Field(max_length=3)
    confidence: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1, max_length=80)
    quality_flags: list[str] = Field(max_length=20)
    report: dict = Field(max_length=30)
    profile: Literal["ecografia_b2c", "mastografia_prototipo"] = "ecografia_b2c"
    image: str = ObjectName
    heatmap: str = ObjectName


class PayloadSelfExam(_Strict):
    ref: str = Field(pattern=r"^e[0-9]{1,4}$")
    content_version: str = Field(min_length=1, max_length=40)
    started_at: datetime
    finished_at: datetime
    noticed_change: Literal["si", "no", "no_segura"]
    note: str | None = Field(default=None, max_length=1000)


class PayloadSymptom(_Strict):
    entry_date: date
    side: Side
    zone: Zone
    symptoms: list[Symptom] = Field(min_length=1, max_length=8)
    intensity: int = Field(ge=0, le=10)
    note: str | None = Field(default=None, max_length=2000)
    self_exam_ref: str | None = Field(default=None, pattern=r"^e[0-9]{1,4}$")
    cycle_day: int | None = Field(default=None, ge=1, le=60)
    in_period: bool | None = None


class PayloadQuestionnaire(_Strict):
    version: str = Field(min_length=1, max_length=40)
    answers: dict = Field(max_length=40)
    risk_factors: list = Field(max_length=40)
    summary_level: str = Field(min_length=1, max_length=40)
    created_at: datetime | None = None


class SharePayload(_Strict):
    format: Literal[1]
    patient: PayloadPatient = Field(default_factory=PayloadPatient)
    analyses: list[PayloadAnalysis] = Field(default_factory=list, max_length=MAX_ANALYSES)
    # 90 días de diario: holgura amplia, pero acotada
    self_exams: list[PayloadSelfExam] = Field(default_factory=list, max_length=200)
    symptoms: list[PayloadSymptom] = Field(default_factory=list, max_length=2000)
    questionnaire: PayloadQuestionnaire | None = None
