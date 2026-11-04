"""Rutas de la médica. Solo `doctor`, siempre con su contexto RLS (TenantDb).

- traspasos de pacientes hacia ella (0014);
- importar un paquete compartido como copia en su tenant (CU-08, ADR 0010);
- sus avisos internos (p. ej. "tienes un paquete").

El panel y el caso llegan después.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import ControlDb, Storage, TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.handovers import HandoverAccepted, PendingHandoverOut
from backend.app.schemas.shares import InboxNoticeOut, ShareImport, ShareImported
from backend.app.services import handovers, notices, share_import
from backend.app.services.auth import AuthContext
from backend.app.services.tenants import NotFoundError

router = APIRouter()

DoctorUser = Annotated[AuthContext, Depends(require_role("doctor"))]
WRITE_LIMIT = Depends(rate_limit("doctor_write", 30, 60))


@router.get("/handovers", response_model=list[PendingHandoverOut])
def list_pending_handovers(auth: DoctorUser, db: TenantDb):
    return handovers.pending_for_me(db, auth)


@router.post(
    "/handovers/{handover_id}/accept", response_model=HandoverAccepted, dependencies=[WRITE_LIMIT]
)
def accept_handover(handover_id: uuid.UUID, auth: DoctorUser, db: TenantDb, request: Request):
    try:
        moved = handovers.accept(db, auth, handover_id, client_ip(request))
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado") from None
    return HandoverAccepted(patients_moved=moved)


@router.post(
    "/shares/import",
    response_model=ShareImported,
    dependencies=[Depends(rate_limit("doctor_share_import", 10, 60))],
)
def import_share(
    data: ShareImport,
    auth: DoctorUser,
    control: ControlDb,
    db: TenantDb,
    storage: Storage,
    request: Request,
):
    result = share_import.import_package(control, db, storage, auth, data.code, client_ip(request))
    return ShareImported(
        patient_id=result.patient_id,
        analyses=result.analyses,
        symptoms=result.symptoms,
        already_imported=result.already_imported,
    )


@router.get("/notices", response_model=list[InboxNoticeOut])
def list_notices(auth: DoctorUser, db: TenantDb):
    return notices.list_own(db, auth)


@router.post("/notices/{notice_id}/read", status_code=204, dependencies=[WRITE_LIMIT])
def read_notice(notice_id: uuid.UUID, auth: DoctorUser, db: TenantDb):
    notices.mark_read(db, auth, notice_id)
