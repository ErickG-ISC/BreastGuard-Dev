"""Rutas de la médica. Solo `doctor`, siempre con su contexto RLS (TenantDb).

Por ahora, los traspasos de pacientes hacia ella (0014); el panel y el caso llegan después.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import TenantDb, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.schemas.handovers import HandoverAccepted, PendingHandoverOut
from backend.app.services import handovers
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
