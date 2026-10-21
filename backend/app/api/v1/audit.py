"""CU-13: un tenant_admin consulta el log de accesos de SU tenant (y solo de su tenant)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.app.api.deps import TenantDb, require_role
from backend.app.schemas.audit import AuditEntryOut
from backend.app.services import audit
from backend.app.services.auth import AuthContext

router = APIRouter()

TenantAdmin = Annotated[AuthContext, Depends(require_role("tenant_admin"))]


@router.get("", response_model=list[AuditEntryOut])
def list_audit_log(
    auth: TenantAdmin,
    db: TenantDb,
    request: Request,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    actor_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    entries = audit.list_entries(
        db, since=since, until=until, actor_id=actor_id, limit=limit, offset=offset
    )
    # Leer la auditoría también queda auditado
    audit.record(
        db,
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        actor_role=auth.role,
        action="audit.read",
        resource_type="audit_log",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return entries
