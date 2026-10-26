"""Administración de la institución (ADR 0008). Solo tenant_admin, solo su tenant.

El tenant SIEMPRE sale del JWT verificado (Scope.for_actor): ninguna ruta recibe un tenant_id
del cliente. Un usuario de otro tenant responde igual que uno inexistente (404).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import ControlDb, Sender, require_role
from backend.app.api.rate_limit import rate_limit
from backend.app.api.v1.admin import ADMIN_ERRORS, admin_errors
from backend.app.schemas.tenants import (
    AdminEventOut,
    AdminEventPage,
    InvitationSent,
    StaffInvite,
    StaffInvited,
    StaffList,
    StaffOut,
    StaffUpdate,
)
from backend.app.services import admin_events, user_admin
from backend.app.services.auth import AuthContext

router = APIRouter()

TenantAdmin = Annotated[AuthContext, Depends(require_role("tenant_admin"))]
WRITE_LIMIT = Depends(rate_limit("institution_write", 60, 60))


def _for_institution(event: AdminEventOut) -> AdminEventOut:
    """La institución ve QUÉ hizo la plataforma, no quién ni desde qué IP."""
    if event.actor_role in ("platform_admin", "system"):
        return event.model_copy(update={"actor_id": None, "ip": None})
    return event


def _scope(auth: AuthContext) -> user_admin.Scope:
    return user_admin.Scope.for_actor(auth)


@router.get("/users", response_model=StaffList)
def list_staff(auth: TenantAdmin, db: ControlDb):
    staff, patients = user_admin.list_staff(db, _scope(auth), auth.tenant_id)
    return StaffList(items=[user_admin.to_out(u) for u in staff], patients=patients)


@router.post(
    "/users",
    response_model=StaffInvited,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE_LIMIT],
)
def invite_staff(
    data: StaffInvite, auth: TenantAdmin, db: ControlDb, sender: Sender, request: Request
):
    try:
        user, sent = user_admin.invite_staff(
            db, _scope(auth), auth.tenant_id, data, sender, client_ip(request)
        )
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return StaffInvited(user=user_admin.to_out(user), email_sent=sent)


@router.patch("/users/{user_id}", response_model=StaffOut, dependencies=[WRITE_LIMIT])
def update_staff(
    user_id: uuid.UUID, data: StaffUpdate, auth: TenantAdmin, db: ControlDb, request: Request
):
    try:
        user = user_admin.update_staff(db, _scope(auth), user_id, data, client_ip(request))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return user_admin.to_out(user)


@router.post(
    "/users/{user_id}/invitation", response_model=InvitationSent, dependencies=[WRITE_LIMIT]
)
def resend_invitation(
    user_id: uuid.UUID, auth: TenantAdmin, db: ControlDb, sender: Sender, request: Request
):
    try:
        sent = user_admin.resend_invitation(db, _scope(auth), user_id, sender, client_ip(request))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return InvitationSent(email_sent=sent)


@router.post(
    "/users/{user_id}/reset-access", response_model=InvitationSent, dependencies=[WRITE_LIMIT]
)
def reset_access(
    user_id: uuid.UUID, auth: TenantAdmin, db: ControlDb, sender: Sender, request: Request
):
    try:
        sent = user_admin.reset_access(db, _scope(auth), user_id, sender, client_ip(request))
    except ADMIN_ERRORS as exc:
        raise admin_errors(exc) from None
    return InvitationSent(email_sent=sent)


@router.get("/events", response_model=AdminEventPage)
def list_events(
    auth: TenantAdmin,
    db: ControlDb,
    action: Annotated[str | None, Query(max_length=64)] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Solo eventos de SU tenant (el alcance lo pone el servidor, no el filtro del cliente)."""
    filters = admin_events.EventFilters(action=action, date_from=date_from, date_to=date_to)
    items, total = admin_events.list_events(
        db, only_tenant=auth.tenant_id, filters=filters, limit=limit, offset=offset
    )
    return AdminEventPage(
        items=[_for_institution(AdminEventOut.model_validate(e)) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )
