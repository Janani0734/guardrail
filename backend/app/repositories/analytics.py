from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActionRequest, Agent, Approval, RateLimitEvent
from app.models.enums import ApprovalStatus, Decision


class AnalyticsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _bucket(self, granularity: str):
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            return func.to_char(func.date_trunc(granularity, ActionRequest.created_at), "YYYY-MM-DD" if granularity == "day" else 'YYYY-MM-DD"T"HH24:00')
        fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%dT%H:00"
        return func.strftime(fmt, ActionRequest.created_at)

    async def totals(self, org_id: uuid.UUID, since: datetime) -> dict[str, int]:
        def cnt(d: Decision):
            return func.coalesce(func.sum(case((ActionRequest.decision == d, 1), else_=0)), 0)

        stmt = select(func.count(), cnt(Decision.ALLOW), cnt(Decision.BLOCK), cnt(Decision.REQUIRE_APPROVAL),
                      func.coalesce(func.sum(ActionRequest.secrets_redacted), 0)).where(
            ActionRequest.organization_id == org_id, ActionRequest.created_at >= since)
        total, allow, block, approval, redacted = (await self.session.execute(stmt)).one()
        return {"total": int(total), "allowed": int(allow), "blocked": int(block),
                "approvals_required": int(approval), "secrets_redacted": int(redacted)}

    async def approval_counts(self, org_id: uuid.UUID, since: datetime) -> dict[str, int]:
        stmt = select(Approval.status, func.count()).where(
            Approval.organization_id == org_id, Approval.created_at >= since).group_by(Approval.status)
        out = {s.value: 0 for s in ApprovalStatus}
        for status, n in (await self.session.execute(stmt)).all():
            out[status.value if hasattr(status, "value") else status] = int(n)
        return out

    async def pending_now(self, org_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Approval).where(
            Approval.organization_id == org_id, Approval.status == ApprovalStatus.PENDING)
        return int((await self.session.execute(stmt)).scalar_one())

    async def rate_limit_events(self, org_id: uuid.UUID, since: datetime) -> int:
        stmt = select(func.count()).select_from(RateLimitEvent).where(
            RateLimitEvent.organization_id == org_id, RateLimitEvent.created_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def timeseries(self, org_id: uuid.UUID, since: datetime, granularity: str):
        bucket = self._bucket(granularity).label("bucket")

        def cnt(d: Decision):
            return func.coalesce(func.sum(case((ActionRequest.decision == d, 1), else_=0)), 0)

        stmt = (
            select(bucket, func.count(), cnt(Decision.ALLOW), cnt(Decision.BLOCK), cnt(Decision.REQUIRE_APPROVAL))
            .where(ActionRequest.organization_id == org_id, ActionRequest.created_at >= since)
            .group_by(bucket).order_by(bucket)
        )
        return [
            {"bucket": b, "total": int(t), "allowed": int(a), "blocked": int(bl), "approvals": int(ap)}
            for b, t, a, bl, ap in (await self.session.execute(stmt)).all()
        ]

    async def agent_activity(self, org_id: uuid.UUID, since: datetime, limit: int = 10):
        def cnt(d: Decision):
            return func.coalesce(func.sum(case((ActionRequest.decision == d, 1), else_=0)), 0)

        stmt = (
            select(Agent.slug, Agent.name, func.count(), cnt(Decision.ALLOW), cnt(Decision.BLOCK),
                   cnt(Decision.REQUIRE_APPROVAL))
            .join(Agent, Agent.id == ActionRequest.agent_id)
            .where(ActionRequest.organization_id == org_id, ActionRequest.created_at >= since)
            .group_by(Agent.slug, Agent.name).order_by(func.count().desc()).limit(limit)
        )
        return [
            {"agent": slug, "name": name, "total": int(t), "allowed": int(a), "blocked": int(b), "approvals": int(ap)}
            for slug, name, t, a, b, ap in (await self.session.execute(stmt)).all()
        ]

    async def top_tools(self, org_id: uuid.UUID, since: datetime, limit: int = 8):
        stmt = (
            select(ActionRequest.tool, func.count(),
                   func.coalesce(func.sum(case((ActionRequest.decision == Decision.BLOCK, 1), else_=0)), 0))
            .where(ActionRequest.organization_id == org_id, ActionRequest.created_at >= since)
            .group_by(ActionRequest.tool).order_by(func.count().desc()).limit(limit)
        )
        return [{"tool": t, "total": int(n), "blocked": int(b)} for t, n, b in (await self.session.execute(stmt)).all()]

    async def top_reason_codes(self, org_id: uuid.UUID, since: datetime, limit: int = 8):
        stmt = (
            select(ActionRequest.reason_code, func.count())
            .where(ActionRequest.organization_id == org_id, ActionRequest.created_at >= since,
                   ActionRequest.decision == Decision.BLOCK)
            .group_by(ActionRequest.reason_code).order_by(func.count().desc()).limit(limit)
        )
        return [{"reason_code": r or "UNKNOWN", "count": int(n)} for r, n in (await self.session.execute(stmt)).all()]
