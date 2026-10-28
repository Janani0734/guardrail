from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActionRequest, Agent, Approval, Policy, PolicyDecision, User
from app.models.enums import ActionStatus, ApprovalStatus, Decision
from app.repositories.common import paginate

SORTABLE = {
    "created_at": ActionRequest.created_at,
    "estimated_cost": ActionRequest.estimated_cost,
    "tool": ActionRequest.tool,
    "environment": ActionRequest.environment,
}


def _history_stmt() -> Select:
    return (
        select(ActionRequest, Agent.slug, PolicyDecision, Policy.name, Approval.id)
        .join(Agent, Agent.id == ActionRequest.agent_id)
        .outerjoin(PolicyDecision, PolicyDecision.action_request_id == ActionRequest.id)
        .outerjoin(Policy, Policy.id == PolicyDecision.policy_id)
        .outerjoin(Approval, Approval.action_request_id == ActionRequest.id)
    )


def history_row(row: Any, with_trace: bool = False) -> dict[str, Any]:
    a, slug, pd, policy_name, approval_id = row
    data = {
        "id": a.id, "action_id": a.action_id, "agent_id": a.agent_id, "agent_slug": slug, "tool": a.tool,
        "environment": a.environment, "arguments": a.arguments, "estimated_cost": a.estimated_cost,
        "reason": a.reason, "decision": a.decision, "status": a.status, "reason_code": a.reason_code,
        "outcome": a.outcome, "secrets_redacted": a.secrets_redacted,
        "policy_id": pd.policy_id if pd else None, "policy_name": policy_name,
        "message": pd.message if pd else None, "approval_id": approval_id, "created_at": a.created_at,
    }
    if with_trace:
        data["trace"] = pd.trace if pd else []
        data["latency_ms"] = a.latency_ms
    return data


class ActionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_external(self, org_id: uuid.UUID, agent_id: uuid.UUID, action_id: str) -> ActionRequest | None:
        stmt = select(ActionRequest).where(
            ActionRequest.organization_id == org_id, ActionRequest.agent_id == agent_id,
            ActionRequest.action_id == action_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_decision(self, action_request_id: uuid.UUID) -> PolicyDecision | None:
        stmt = select(PolicyDecision).where(PolicyDecision.action_request_id == action_request_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, org_id: uuid.UUID, request_id: uuid.UUID) -> ActionRequest | None:
        stmt = select(ActionRequest).where(ActionRequest.id == request_id, ActionRequest.organization_id == org_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_detail(self, org_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = _history_stmt().where(ActionRequest.id == request_id, ActionRequest.organization_id == org_id)
        row = (await self.session.execute(stmt)).first()
        return history_row(row, with_trace=True) if row else None

    async def list(
        self, org_id: uuid.UUID, page: int, page_size: int, *, agent_id: uuid.UUID | None = None,
        tool: str | None = None, environment: str | None = None, decision: Decision | None = None,
        status: ActionStatus | None = None, search: str | None = None, date_from: datetime | None = None,
        date_to: datetime | None = None, sort_by: str = "created_at", order: str = "desc",
    ):
        stmt = _history_stmt().where(ActionRequest.organization_id == org_id)
        if agent_id:
            stmt = stmt.where(ActionRequest.agent_id == agent_id)
        if tool:
            stmt = stmt.where(ActionRequest.tool.ilike(f"%{tool.lower()}%"))
        if environment:
            stmt = stmt.where(ActionRequest.environment == environment.lower())
        if decision:
            stmt = stmt.where(ActionRequest.decision == decision)
        if status:
            stmt = stmt.where(ActionRequest.status == status)
        if search:
            stmt = stmt.where(ActionRequest.action_id.ilike(f"%{search}%"))
        if date_from:
            stmt = stmt.where(ActionRequest.created_at >= date_from)
        if date_to:
            stmt = stmt.where(ActionRequest.created_at <= date_to)
        col = SORTABLE.get(sort_by, ActionRequest.created_at)
        stmt = stmt.order_by(col.asc() if order == "asc" else col.desc(), ActionRequest.id)
        rows, total = await paginate(self.session, stmt, page, page_size)
        return [history_row(r) for r in rows], total

    def add(self, obj: Any) -> Any:
        self.session.add(obj)
        return obj


def _approval_stmt() -> Select:
    decider = User
    return (
        select(Approval, ActionRequest, Agent.slug, Policy.name, decider.email)
        .join(ActionRequest, ActionRequest.id == Approval.action_request_id)
        .join(Agent, Agent.id == ActionRequest.agent_id)
        .outerjoin(Policy, Policy.id == Approval.policy_id)
        .outerjoin(decider, decider.id == Approval.decided_by)
    )


def approval_row(row: Any) -> dict[str, Any]:
    ap, ar, slug, policy_name, decider_email = row
    return {
        "id": ap.id, "action_request_id": ar.id, "action_id": ar.action_id, "agent_slug": slug, "tool": ar.tool,
        "environment": ar.environment, "estimated_cost": ar.estimated_cost, "arguments": ar.arguments,
        "reason": ar.reason, "message": ap.message, "status": ap.status, "expires_at": ap.expires_at,
        "policy_id": ap.policy_id, "policy_name": policy_name, "decided_by": ap.decided_by,
        "decided_by_email": decider_email, "decided_at": ap.decided_at, "decision_reason": ap.decision_reason,
        "created_at": ap.created_at,
    }


class ApprovalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID, approval_id: uuid.UUID, *, for_update: bool = False) -> Approval | None:
        stmt = select(Approval).where(Approval.id == approval_id, Approval.organization_id == org_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_action(self, action_request_id: uuid.UUID) -> Approval | None:
        stmt = select(Approval).where(Approval.action_request_id == action_request_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_row(self, org_id: uuid.UUID, approval_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = _approval_stmt().where(Approval.id == approval_id, Approval.organization_id == org_id)
        row = (await self.session.execute(stmt)).first()
        return approval_row(row) if row else None

    async def list(self, org_id: uuid.UUID, page: int, page_size: int, status: ApprovalStatus | None,
                   agent_id: uuid.UUID | None = None, environment: str | None = None):
        stmt = _approval_stmt().where(Approval.organization_id == org_id)
        if status:
            stmt = stmt.where(Approval.status == status)
        if status == ApprovalStatus.PENDING:
            stmt = stmt.where(Approval.expires_at > datetime.now(UTC))  # overdue rows await the worker; don't show them
        if agent_id:
            stmt = stmt.where(ActionRequest.agent_id == agent_id)
        if environment:
            stmt = stmt.where(ActionRequest.environment == environment.lower())
        order = Approval.expires_at.asc() if status == ApprovalStatus.PENDING else Approval.created_at.desc()
        rows, total = await paginate(self.session, stmt.order_by(order), page, page_size)
        return [approval_row(r) for r in rows], total

    async def list_due_for_expiry(self, now: datetime, limit: int = 200) -> list[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.status == ApprovalStatus.PENDING, Approval.expires_at <= now)
            .order_by(Approval.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    def add(self, approval: Approval) -> Approval:
        self.session.add(approval)
        return approval
