"""CU-02: análisis de ecografías para la paciente (subir, historial, detalle y eliminar)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import Storage, TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.ml.deps import Inference
from backend.app.schemas.analysis import AnalysisDetailOut, AnalysisOut, AnalysisPage
from backend.app.services import analyses
from backend.app.services.auth import AuthContext
from backend.app.services.images import read_and_validate_image

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]


@router.post(
    "",
    response_model=AnalysisDetailOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("analyses_create", 10, 60))],
)
async def create_analysis(
    file: Annotated[UploadFile, File()],
    auth: PatientUser,
    db: TenantDb,
    storage: Storage,
    inference: Inference,
    request: Request,
):
    image = await read_and_validate_image(file)
    ip = client_ip(request)
    created = await analyses.create(db, storage, inference, auth, image, ip)
    analysis, image_url, heatmap_url, ttl = analyses.get_with_urls(
        db, storage, auth, created.id, ip
    )
    return AnalysisDetailOut(
        **AnalysisOut.model_validate(analysis).model_dump(),
        image_url=image_url,
        heatmap_url=heatmap_url,
        url_expires_in=ttl,
    )


@router.get("", response_model=AnalysisPage)
def list_analyses(
    auth: PatientUser,
    db: TenantDb,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = analyses.list_page(db, auth, limit, offset, client_ip(request))
    return AnalysisPage(
        items=[AnalysisOut.model_validate(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{analysis_id}", response_model=AnalysisDetailOut)
def get_analysis(
    analysis_id: uuid.UUID, auth: PatientUser, db: TenantDb, storage: Storage, request: Request
):
    analysis, image_url, heatmap_url, ttl = analyses.get_with_urls(
        db, storage, auth, analysis_id, client_ip(request)
    )
    return AnalysisDetailOut(
        **AnalysisOut.model_validate(analysis).model_dump(),
        image_url=image_url,
        heatmap_url=heatmap_url,
        url_expires_in=ttl,
    )


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(
    analysis_id: uuid.UUID, auth: PatientUser, db: TenantDb, storage: Storage, request: Request
):
    analyses.delete(db, storage, auth, analysis_id, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
