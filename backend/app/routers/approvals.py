import uuid

from fastapi import APIRouter, Query

from app.models.enums import ApprovalStatus
from app.repositories.actions import ApprovalRepository
from app.routers.deps import AgentAuth, Manager, RedisDep, SessionDep, Viewer
from app.schemas.actions import VerifyTokenRequest, VerifyTokenResponse
from app.schemas.approvals import ApprovalOut, DecisionRequest
from app.schemas.common import Page
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


@router.get("", response_model=Page[ApprovalOut])
async def list_approvals(
    p: Viewer, session: SessionDep, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: ApprovalStatus | None = None, agent_id: uuid.UUID | None = None,
    environment: str | None = Query(None, max_length=32),
):
    rows, total = await ApprovalRepository(session).list(p.org_id, page, page_size, status, agent_id, environment)
    return Page.build([ApprovalOut(**r) for r in rows], total, page, page_size)


@router.post("/verify-token", response_model=VerifyTokenResponse, summary="Agent: consume a one-time approval token")
async def verify_token(data: VerifyTokenRequest, auth: AgentAuth, session: SessionDep, redis: RedisDep):
    _, agent = auth
    return await ApprovalService(session, redis).verify_token(agent, data.token)


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: uuid.UUID, p: Viewer, session: SessionDep, redis: RedisDep):
    return ApprovalOut(**await ApprovalService(session, redis).get(p.org_id, approval_id))


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(approval_id: uuid.UUID, data: DecisionRequest, p: Manager, session: SessionDep, redis: RedisDep):
    row = await ApprovalService(session, redis).decide(
        org_id=p.org_id, approval_id=approval_id, user_id=p.user_id, user_email=p.email, approve=True, reason=data.reason)
    return ApprovalOut(**row)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(approval_id: uuid.UUID, data: DecisionRequest, p: Manager, session: SessionDep, redis: RedisDep):
    row = await ApprovalService(session, redis).decide(
        org_id=p.org_id, approval_id=approval_id, user_id=p.user_id, user_email=p.email, approve=False, reason=data.reason)
    return ApprovalOut(**row)
