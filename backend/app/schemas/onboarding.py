import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.content.questionnaire import AnswersV1


class ConsentOut(BaseModel):
    version: str
    text: str
    sha256: str


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    description: str
    price_label: str
    features: list[str]
    simulated: bool = True  # no hay pasarela de pago


class SubscriptionOut(BaseModel):
    plan: PlanOut
    status: str
    started_at: datetime


class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: str = Field(min_length=1, max_length=50)


class QuestionnaireDefinitionOut(BaseModel):
    version: str
    questions: list[dict]


class QuestionnaireIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    answers: AnswersV1


class RiskFactorOut(BaseModel):
    code: str
    label: str
    kind: str


class QuestionnaireOut(BaseModel):
    id: uuid.UUID
    version: str
    created_at: datetime
    factors: list[RiskFactorOut]
    level: str
    message: str
    disclaimer: str
