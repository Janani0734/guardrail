import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.exceptions import NotFound
from app.models.enums import ActionStatus, Decision
from app.repositories.actions import ActionRepository
from app.routers.deps import AgentAuth, RedisDep, SessionDep, Viewer
from app.schemas.actions import (
    ActionDetailOut, ActionHistoryOut, ActionStatusResponse, AllowResponse, ApprovalRequiredResponse, BlockResponse,
    EvaluateRequest, OutcomeRequest,
)
from app.schemas.common import Page
from app.services.approval_service import ApprovalService
from app.services.evaluation_service import EvaluationService

router = APIRouter(tags=["actions"])

EVAL_RESPONSES = {
    200: {"model": AllowResponse | BlockResponse, "description": "ALLOW or BLOCK decision"},
    202: {"model": ApprovalRequiredResponse, "description": "REQUIRE_APPROVAL: poll /status until decided"},
    429: {"model": BlockResponse, "description": "Rate limit exceeded; see Retry-After"},
}


@router.post("/v1/actions/evaluate", responses=EVAL_RESPONSES, summary="Evaluate an agent action")
async def evaluate_action(data: EvaluateRequest, auth: AgentAuth, session: SessionDep, redis: RedisDep):
    key, agent = auth
    result = await EvaluationService(session, redis).evaluate(key, agent, data)
    return JSONResponse(status_code=result.status_code, content=jsonable_encoder(result.body), headers=result.headers)


@router.get("/v1/actions/{action_id}/status", response_model=ActionStatusResponse)
async def action_status(action_id: str, auth: AgentAuth, session: SessionDep, redis: RedisDep):
    _, agent = auth
    return await ApprovalService(session, redis).agent_status(agent, action_id)


@router.post("/v1/actions/{action_id}/outcome")
async def report_outcome(action_id: str, data: OutcomeRequest, auth: AgentAuth, session: SessionDep, redis: RedisDep):
    _, agent = auth
    return await EvaluationService(session, redis).report_outcome(agent, action_id, data)


@router.get("/v1/action-history", response_model=Page[ActionHistoryOut], tags=["dashboard"])
async def action_history(
    p: Viewer, session: SessionDep, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    agent_id: uuid.UUID | None = None, tool: str | None = Query(None, max_length=128),
    environment: str | None = Query(None, max_length=32), decision: Decision | None = None,
    status: ActionStatus | None = None, search: str | None = Query(None, max_length=128),
    date_from: datetime | None = None, date_to: datetime | None = None,
    sort_by: str = Query("created_at", pattern="^(created_at|estimated_cost|tool|environment)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    rows, total = await ActionRepository(session).list(
        p.org_id, page, page_size, agent_id=agent_id, tool=tool, environment=environment, decision=decision,
        status=status, search=search, date_from=date_from, date_to=date_to, sort_by=sort_by, order=order)
    return Page.build([ActionHistoryOut(**r) for r in rows], total, page, page_size)


@router.get("/v1/action-history/{request_id}", response_model=ActionDetailOut, tags=["dashboard"])
async def action_detail(request_id: uuid.UUID, p: Viewer, session: SessionDep):
    row = await ActionRepository(session).get_detail(p.org_id, request_id)
    if not row:
        raise NotFound("Action not found", code="ACTION_NOT_FOUND")
    return ActionDetailOut(**row)
