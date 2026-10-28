import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Response, status

from app.models.enums import ActorType
from app.repositories.audit import AuditRepository
from app.routers.deps import Admin, RedisDep, SessionDep, Viewer
from app.schemas.admin import (
    AuditLogOut, AuditVerifyOut, MemberCreate, MemberOut, MemberRoleUpdate, OrganizationUpdate,
)
from app.schemas.auth import OrganizationOut
from app.schemas.common import Page
from app.services.analytics_service import AnalyticsService
from app.services.audit_service import AuditService
from app.services.member_service import MemberService

router = APIRouter(prefix="/v1", tags=["admin"])


@router.get("/audit-logs", response_model=Page[AuditLogOut])
async def list_audit_logs(
    p: Viewer, session: SessionDep, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    event_type: str | None = Query(None, max_length=64), entity_type: str | None = Query(None, max_length=64),
    entity_id: str | None = Query(None, max_length=64), actor_type: ActorType | None = None,
    date_from: datetime | None = None, date_to: datetime | None = None,
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    rows, total = await AuditRepository(session).list(
        p.org_id, page, page_size, event_type=event_type, entity_type=entity_type, entity_id=entity_id,
        actor_type=actor_type.value if actor_type else None, date_from=date_from, date_to=date_to, order=order)
    return Page.build([AuditLogOut.model_validate(r) for r in rows], total, page, page_size)


@router.get("/audit-logs/verify", response_model=AuditVerifyOut)
async def verify_audit_chain(p: Admin, session: SessionDep):
    valid, checked, bad = await AuditService(session).verify_chain(p.org_id)
    return AuditVerifyOut(valid=valid, checked=checked, first_invalid_seq=bad)


@router.get("/analytics")
async def analytics(p: Viewer, session: SessionDep, redis: RedisDep, days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    return await AnalyticsService(session, redis).overview(p.org_id, days)


@router.get("/organization", response_model=OrganizationOut)
async def get_organization(p: Viewer, session: SessionDep):
    return await MemberService(session).organization(p)


@router.patch("/organization", response_model=OrganizationOut)
async def rename_organization(data: OrganizationUpdate, p: Admin, session: SessionDep):
    return await MemberService(session).rename(p, data.name)


@router.get("/members", response_model=list[MemberOut])
async def list_members(p: Viewer, session: SessionDep):
    return await MemberService(session).list(p)


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def add_member(data: MemberCreate, p: Admin, session: SessionDep):
    return await MemberService(session).create(p, data)


@router.patch("/members/{user_id}", response_model=MemberOut)
async def change_role(user_id: uuid.UUID, data: MemberRoleUpdate, p: Admin, session: SessionDep):
    return await MemberService(session).set_role(p, user_id, data.role)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: uuid.UUID, p: Admin, session: SessionDep):
    await MemberService(session).remove(p, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
