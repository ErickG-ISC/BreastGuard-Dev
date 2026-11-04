"""CU-07: la paciente comparte, consulta y revoca paquetes para su médica (ADR 0010).

Solo pacientes, con su contexto RLS (TenantDb). La importación es de la médica (CU-08).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import Sender, Storage, TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.content.share_consent import current_share_consent
from backend.app.schemas.shares import ShareConsentOut, ShareCreate, ShareCreated, ShareList
from backend.app.services import shares
from backend.app.services.auth import AuthContext

router = APIRouter()

PatientUser = Annotated[AuthContext, Depends(require_role("patient"))]
CREATE_LIMIT = Depends(rate_limit("shares_create", 5, 60))
WRITE_LIMIT = Depends(rate_limit("shares_write", 30, 60))


@router.get("/consent", response_model=ShareConsentOut)
def get_consent(auth: PatientUser):
    consent = current_share_consent()
    return ShareConsentOut(version=consent.version, text=consent.text, sha256=consent.sha256)


@router.post(
    "",
    response_model=ShareCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CREATE_LIMIT],
)
def create_share(
    data: ShareCreate,
    auth: PatientUser,
    db: TenantDb,
    storage: Storage,
    sender: Sender,
    request: Request,
    response: Response,
):
    # El código solo se muestra una vez: que ningún intermediario lo guarde
    response.headers["Cache-Control"] = "no-store"
    return shares.create(db, storage, sender, auth, data, client_ip(request))


@router.get("", response_model=ShareList)
def list_shares(auth: PatientUser, db: TenantDb):
    return ShareList(items=shares.list_own(db, auth))


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE_LIMIT])
def revoke_share(
    package_id: uuid.UUID, auth: PatientUser, db: TenantDb, storage: Storage, request: Request
):
    shares.revoke(db, storage, auth, package_id, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
