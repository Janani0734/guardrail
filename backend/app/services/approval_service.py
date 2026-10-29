"""Human-in-the-loop approvals.

State machine:  PENDING --approve--> APPROVED
                PENDING --reject---> REJECTED
                PENDING --timeout--> EXPIRED      (worker, or lazily when someone touches an overdue approval)
All transitions are guarded by SELECT ... FOR UPDATE so two admins (or an admin and the expiry worker) can never
both "win". Redis holds the fast-read state and one-time approval tokens; PostgreSQL is authoritative.
"""
import hmac
import uuid
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import Conflict, NotFound
from app.core.logging import get_logger
from app.core.security import action_fingerprint, generate_approval_token, hash_token
from app.models import Agent, Approval
from app.models.base import utcnow
from app.models.enums import ActionStatus, ActorType, ApprovalStatus
from app.repositories.actions import ActionRepository, ApprovalRepository
from app.schemas.actions import ActionStatusResponse, VerifyTokenRequest, VerifyTokenResponse
from app.services.audit_service import AuditService
from app.services.cache import bump_analytics_version
from app.utils import redis_keys

log = get_logger(__name__)


async def publish_state(redis: Redis, approval: Approval, action_id: str, token: str | None = None) -> None:
    key = redis_keys.approval_state(approval.id)
    mapping = {
        "status": approval.status.value, "action_id": action_id, "expires_at": approval.expires_at.isoformat(),
        "decision_reason": approval.decision_reason or "",
    }
    if token:
        mapping["token"] = token
    pipe = redis.pipeline(transaction=True)
    pipe.hset(key, mapping=mapping)
    ttl = max(int((approval.expires_at - utcnow()).total_seconds()), 0) + get_settings().approval_token_ttl_seconds
    pipe.expire(key, max(ttl, 60))
    await pipe.execute()


class ApprovalService:
    def __init__(self, session: AsyncSession, redis: Redis):
        self.session = session
        self.redis = redis
        self.approvals = ApprovalRepository(session)
        self.actions = ActionRepository(session)
        self.audit = AuditService(session)
        self.settings = get_settings()

    async def get(self, org_id: uuid.UUID, approval_id: uuid.UUID) -> dict[str, Any]:
        row = await self.approvals.get_row(org_id, approval_id)
        if not row:
            raise NotFound("Approval not found", code="APPROVAL_NOT_FOUND")
        return row

    async def decide(self, *, org_id: uuid.UUID, approval_id: uuid.UUID, user_id: uuid.UUID, user_email: str,
                     approve: bool, reason: str | None) -> dict[str, Any]:
        approval = await self.approvals.get(org_id, approval_id, for_update=True)
        if not approval:  # same 404 whether it doesn't exist or belongs to another org (no IDOR oracle)
            raise NotFound("Approval not found", code="APPROVAL_NOT_FOUND")
        action = await self.actions.get(org_id, approval.action_request_id)
        now = utcnow()
        if approval.status != ApprovalStatus.PENDING:
            raise Conflict(f"Approval is already {approval.status.value}", code="APPROVAL_NOT_PENDING")
        if approval.expires_at <= now:
            await self._expire_one(approval, action, now)
            await self.session.commit()
            await self._publish_safe(approval, action.action_id)
            raise Conflict("Approval has expired", code="APPROVAL_EXPIRED")

        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_by, approval.decided_at, approval.decision_reason = user_id, now, reason
        action.status = ActionStatus.APPROVED if approve else ActionStatus.REJECTED
        await self.audit.log(
            org_id=org_id, actor_type=ActorType.USER, actor_id=user_id, actor_label=user_email,
            event_type="APPROVAL_APPROVED" if approve else "APPROVAL_REJECTED", entity_type="approval",
            entity_id=approval.id, details={"action_id": action.action_id, "tool": action.tool,
                                            "environment": action.environment, "reason": reason},
        )
        await self.session.commit()

        token = None
        try:
            if approve:
                token = generate_approval_token()
                # The token is bound to approval, action, agent and the keyed fingerprint of (tool, environment,
                # raw arguments) captured at evaluation time. Fields are pipe-separated; none can contain "|".
                await self.redis.set(
                    redis_keys.approval_token(hash_token(token)),
                    f"{approval.id}|{action.action_id}|{action.agent_id}|{action.fingerprint}",
                    ex=self.settings.approval_token_ttl_seconds,
                )
            await publish_state(self.redis, approval, action.action_id, token)
            await bump_analytics_version(self.redis, org_id)
            if not approve:
                await self._count_rejection(action)
        except RedisError:
            log.warning("redis side effects after approval decision failed", exc_info=True)
        return await self.get(org_id, approval_id)

    async def _count_rejection(self, action) -> None:
        from app.repositories.policies import PolicyRepository
        from app.services.evaluation_service import repeat_config
        from app.services.rate_limit_service import RepeatTracker

        _, cfg = repeat_config(await PolicyRepository(self.session).list_active(action.organization_id))
        await RepeatTracker(self.redis).record_failure(action.organization_id, action.agent_id, action.fingerprint, **cfg)

    async def _expire_one(self, approval: Approval, action, now: datetime) -> None:
        approval.status = ApprovalStatus.EXPIRED
        approval.decided_at = now
        approval.decision_reason = "Expired without a decision"
        action.status = ActionStatus.EXPIRED
        await self.audit.log(
            org_id=approval.organization_id, actor_type=ActorType.SYSTEM, actor_label="approval-expiry-worker",
            event_type="APPROVAL_EXPIRED", entity_type="approval", entity_id=approval.id,
            details={"action_id": action.action_id, "tool": action.tool, "expired_at": approval.expires_at.isoformat()},
        )

    async def _publish_safe(self, approval: Approval, action_id: str) -> None:
        try:
            await publish_state(self.redis, approval, action_id)
            await bump_analytics_version(self.redis, approval.organization_id)
        except RedisError:
            log.warning("could not publish approval state", exc_info=True)

    async def expire_due(self, batch: int = 200) -> int:
        """Idempotent and safe to run on many workers: rows are claimed with FOR UPDATE SKIP LOCKED."""
        now = utcnow()
        due = await self.approvals.list_due_for_expiry(now, batch)
        done: list[tuple[Approval, str]] = []
        for approval in due:
            action = await self.actions.get(approval.organization_id, approval.action_request_id)
            await self._expire_one(approval, action, now)
            done.append((approval, action.action_id))
        await self.session.commit()
        for approval, action_id in done:
            await self._publish_safe(approval, action_id)
        return len(done)

    # ----------------------------------------------------------- agent-facing
    async def agent_status(self, agent: Agent, action_id: str) -> ActionStatusResponse:
        action = await self.actions.get_by_external(agent.organization_id, agent.id, action_id)
        if not action:
            raise NotFound("Action not found", code="ACTION_NOT_FOUND")
        approval = await self.approvals.get_for_action(action.id)
        if approval and approval.status == ApprovalStatus.PENDING and approval.expires_at <= utcnow():
            await self._expire_one(approval, action, utcnow())  # lazy expiry: don't wait for the worker
            await self.session.commit()
            await self._publish_safe(approval, action_id)
        token = None
        if approval and approval.status == ApprovalStatus.APPROVED:
            token = await self._pop_token(approval)
        return ActionStatusResponse(
            action_id=action.action_id, decision=action.decision, status=action.status,
            approval_id=str(approval.id) if approval else None, approval_status=approval.status if approval else None,
            expires_at=approval.expires_at if approval else None,
            decision_reason=approval.decision_reason if approval else None, approval_token=token,
        )

    async def _pop_token(self, approval: Approval) -> str | None:
        key = redis_keys.approval_state(approval.id)
        try:
            pipe = self.redis.pipeline(transaction=True)
            pipe.hget(key, "token")
            pipe.hdel(key, "token")
            token, _ = await pipe.execute()
            return token or None
        except RedisError:
            return None

    async def verify_token(self, agent: Agent, data: VerifyTokenRequest) -> VerifyTokenResponse:
        """One-time use: GETDEL makes the check-and-consume atomic, so a token can authorise exactly one execution.

        Any presentation consumes the token, even a mismatched one: a token that was offered for the wrong agent,
        action, tool or arguments is burned and a fresh approval is needed. Binding checks are exact."""
        try:
            raw = await self.redis.getdel(redis_keys.approval_token(hash_token(data.token)))
        except RedisError:
            return VerifyTokenResponse(valid=False, reason="STATE_STORE_UNAVAILABLE")
        if not raw:
            return VerifyTokenResponse(valid=False, reason="UNKNOWN_OR_EXPIRED")
        parts = raw.split("|")
        approval_id, action_id, agent_id = parts[0], parts[1], parts[2]
        bound_fp = parts[3] if len(parts) > 3 else None  # tokens minted before request binding existed have none
        if agent_id != str(agent.id):
            return VerifyTokenResponse(valid=False, reason="AGENT_MISMATCH")
        if data.action_id is not None and data.action_id != action_id:
            return VerifyTokenResponse(valid=False, reason="ACTION_MISMATCH")
        if data.binds_request:
            presented = action_fingerprint(data.tool, data.environment, data.arguments)
            if bound_fp is None or not hmac.compare_digest(bound_fp, presented):
                return VerifyTokenResponse(valid=False, reason="REQUEST_MISMATCH")
        return VerifyTokenResponse(valid=True, action_id=action_id, approval_id=approval_id)
