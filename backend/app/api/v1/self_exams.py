"""CU-03: autoexploración guiada. La guía es pública; los registros son solo de la paciente."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.content.self_exam import current_guide
from backend.app.schemas.self_exam import GuideOut, SelfExamFinishIn, SelfExamOut, SelfExamPage
from backend.app.services import self_exams
from backend.app.services.auth import AuthContext

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]
WRITE_LIMIT = Depends(rate_limit("self_exams_write", 30, 60))
READ_LIMIT = Depends(rate_limit("self_exams_read", 60, 60))


@router.get("/self-exam/guide", response_model=GuideOut)
def get_guide():
    return current_guide()


@router.post(
    "/self-exams",
    response_model=SelfExamOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def start_self_exam(auth: PatientUser, db: TenantDb, request: Request):
    return self_exams.start(db, auth, client_ip(request))


@router.post("/self-exams/{exam_id}/finish", response_model=SelfExamOut, dependencies=[WRITE_LIMIT])
def finish_self_exam(
    exam_id: uuid.UUID, data: SelfExamFinishIn, auth: PatientUser, db: TenantDb, request: Request
):
    return self_exams.finish(db, auth, exam_id, data, client_ip(request))


@router.get("/self-exams", response_model=SelfExamPage, dependencies=[READ_LIMIT])
def list_self_exams(
    auth: PatientUser,
    db: TenantDb,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = self_exams.list_page(db, auth, limit, offset, client_ip(request))
    return SelfExamPage(
        items=[SelfExamOut.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# Antes de /self-exams/{exam_id}: "latest" no es un UUID
@router.get("/self-exams/latest", response_model=SelfExamOut, dependencies=[READ_LIMIT])
def latest_self_exam(auth: PatientUser, db: TenantDb, request: Request):
    return self_exams.latest(db, auth, client_ip(request))


@router.get("/self-exams/{exam_id}", response_model=SelfExamOut, dependencies=[READ_LIMIT])
def get_self_exam(exam_id: uuid.UUID, auth: PatientUser, db: TenantDb, request: Request):
    return self_exams.get(db, auth, exam_id, client_ip(request))


@router.delete(
    "/self-exams/{exam_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE_LIMIT]
)
def delete_self_exam(exam_id: uuid.UUID, auth: PatientUser, db: TenantDb, request: Request):
    self_exams.delete(db, auth, exam_id, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
