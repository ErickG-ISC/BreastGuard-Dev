"""CU-01: consentimiento vigente, planes simulados, suscripción y cuestionario."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import ControlDb, TenantDb, require_role
from backend.app.content.consent import current_consent
from backend.app.content.questionnaire import QUESTIONNAIRE_VERSION, QUESTIONS
from backend.app.models.control import Plan, Subscription
from backend.app.schemas.onboarding import (
    ConsentOut,
    PlanOut,
    QuestionnaireDefinitionOut,
    QuestionnaireIn,
    QuestionnaireOut,
    SubscriptionOut,
    SubscriptionUpdate,
)
from backend.app.services import questionnaire
from backend.app.services.auth import AuthContext

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]


@router.get("/consent/current", response_model=ConsentOut)
def get_current_consent():
    consent = current_consent()
    return ConsentOut(version=consent.version, text=consent.text, sha256=consent.sha256)


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: ControlDb):
    return db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort)).all()


def _subscription_out(db, subscription: Subscription) -> SubscriptionOut:
    plan = db.get(Plan, subscription.plan_code)
    return SubscriptionOut(
        plan=PlanOut.model_validate(plan),
        status=subscription.status,
        started_at=subscription.started_at,
    )


@router.get("/subscription/me", response_model=SubscriptionOut)
def get_my_subscription(auth: PatientUser, db: ControlDb):
    subscription = db.scalars(
        select(Subscription).where(Subscription.user_id == auth.user_id)
    ).first()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sin plan asignado")
    return _subscription_out(db, subscription)


@router.put("/subscription/me", response_model=SubscriptionOut)
def change_my_plan(data: SubscriptionUpdate, auth: PatientUser, db: ControlDb):
    """Cambio de plan SIMULADO: no hay cobro ni datos de pago."""
    plan = db.get(Plan, data.plan_code)
    if plan is None or not plan.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Plan no disponible"
        )
    subscription = db.scalars(
        select(Subscription).where(Subscription.user_id == auth.user_id)
    ).first()
    if subscription is None:
        subscription = Subscription(user_id=auth.user_id, plan_code=plan.code)
        db.add(subscription)
    else:
        subscription.plan_code = plan.code
        subscription.started_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Intenta de nuevo en un momento"
        ) from None
    db.refresh(subscription)
    return _subscription_out(db, subscription)


@router.get("/questionnaire/current", response_model=QuestionnaireDefinitionOut)
def get_questionnaire_definition(auth: PatientUser):
    return QuestionnaireDefinitionOut(version=QUESTIONNAIRE_VERSION, questions=QUESTIONS)


@router.post(
    "/questionnaires", response_model=QuestionnaireOut, status_code=status.HTTP_201_CREATED
)
def submit_questionnaire(data: QuestionnaireIn, auth: PatientUser, db: TenantDb, request: Request):
    return questionnaire.submit(db, auth, data.version, data.answers, client_ip(request))


@router.get("/questionnaires/latest", response_model=QuestionnaireOut)
def get_latest_questionnaire(auth: PatientUser, db: TenantDb, request: Request):
    return questionnaire.latest(db, auth, client_ip(request))
