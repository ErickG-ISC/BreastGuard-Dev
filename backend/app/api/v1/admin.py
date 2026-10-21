"""Administración de plataforma (CU-12). Solo platform_admin; solo esquema control."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.api.client_ip import client_ip
from backend.app.api.deps import ControlDb, require_role
from backend.app.schemas.tenants import (
    ActiveUpdate,
    AdminUserOut,
    IsolationReport,
    TenantCreate,
    TenantCreated,
    TenantOut,
    TenantUserCreate,
)
from backend.app.services import tenants as service
from backend.app.services.auth import AuthContext

router = APIRouter()

PlatformAdmin = Annotated[AuthContext, Depends(require_role("platform_admin"))]


def _client_ip(request: Request) -> str | None:
    return client_ip(request)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado")


@router.post("/tenants", response_model=TenantCreated, status_code=status.HTTP_201_CREATED)
def create_tenant(data: TenantCreate, auth: PlatformAdmin, db: ControlDb, request: Request):
    try:
        tenant, admin = service.create_tenant(db, auth, data, _client_ip(request))
    except service.ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return TenantCreated(tenant=TenantOut.model_validate(tenant), admin_user_id=admin.id)


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(auth: PlatformAdmin, db: ControlDb):
    return service.list_tenants(db)


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: uuid.UUID, data: ActiveUpdate, auth: PlatformAdmin, db: ControlDb, request: Request
):
    try:
        return service.set_tenant_active(db, auth, tenant_id, data.is_active, _client_ip(request))
    except service.NotFoundError:
        raise _not_found() from None
    except service.InvalidOperationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None


@router.post(
    "/tenants/{tenant_id}/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED
)
def create_tenant_user(
    tenant_id: uuid.UUID,
    data: TenantUserCreate,
    auth: PlatformAdmin,
    db: ControlDb,
    request: Request,
):
    try:
        return service.create_tenant_user(db, auth, tenant_id, data, _client_ip(request))
    except service.NotFoundError:
        raise _not_found() from None
    except service.ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except service.InvalidOperationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: uuid.UUID, data: ActiveUpdate, auth: PlatformAdmin, db: ControlDb, request: Request
):
    try:
        return service.set_user_active(db, auth, user_id, data.is_active, _client_ip(request))
    except service.NotFoundError:
        raise _not_found() from None


@router.post("/tenants/{tenant_id}/isolation-check", response_model=IsolationReport)
def isolation_check(tenant_id: uuid.UUID, auth: PlatformAdmin):
    try:
        return service.isolation_check(auth, tenant_id)
    except service.NotFoundError:
        raise _not_found() from None
