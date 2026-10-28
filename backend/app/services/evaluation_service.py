"""The hot path: POST /v1/actions/evaluate.

Pipeline: agent binding -> idempotency -> redaction -> temp-block -> rate limit -> policy engine -> persist -> Redis side effects.
PostgreSQL is written first and is authoritative; Redis side effects happen after commit and are best-effort.
"""
import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import Conflict, Forbidden, NotFound, ServiceUnavailable
from app.core.logging import get_logger
from app.core.security import fingerprint
from app.models import ActionRequest, Agent, ApiKey, Approval, Policy, PolicyDecision, RateLimitEvent
from app.models.base import utcnow
from app.models.enums import ActionOutcome, ActionStatus, ActorType, AgentStatus, ApprovalStatus, Decision, PolicyType
from app.repositories.actions import ActionRepository, ApprovalRepository
from app.repositories.agents import ToolRepository
from app.repositories.policies import PolicyRepository
from app.schemas.actions import EvaluateRequest, OutcomeRequest
from app.services import approval_service
from app.services.audit_service import AuditService
from app.services.cache import bump_analytics_version
from app.services.policy_engine import ActionContext, EngineResult, evaluate
from app.services.rate_limit_service import RateLimiter, RepeatTracker
from app.utils import redis_keys
from app.utils.redaction import redact_text, redact_value

log = get_logger(__name__)

TRANSIENT_REASONS = {"RATE_LIMIT_EXCEEDED", "REPEATED_ACTION_BLOCKED"}
STATUS_FOR = {
    Decision.ALLOW: ActionStatus.ALLOWED,
    Decision.BLOCK: ActionStatus.BLOCKED,
    Decision.REQUIRE_APPROVAL: ActionStatus.PENDING_APPROVAL,
}


@dataclass
class EvalResult:
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


def _iso(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def build_body(action_id: str, decision: Decision, reason_code: str, message: str | None, policy_id,
               approval: Approval | None) -> dict[str, Any]:
    pid = str(policy_id) if policy_id else None
    if decision == Decision.ALLOW:
        return {"decision": "ALLOW", "action_id": action_id, "policy_id": pid, "expires_at": None}
    if decision == Decision.BLOCK:
        return {"decision": "BLOCK", "action_id": action_id, "reason_code": reason_code, "message": message,
                "policy_id": pid}
    assert approval is not None
    return {"decision": "REQUIRE_APPROVAL", "action_id": action_id, "approval_id": str(approval.id),
            "expires_at": _iso(approval.expires_at), "message": message, "policy_id": pid}


def repeat_config(policies: list[Policy]) -> tuple[Policy | None, dict[str, int]]:
    s = get_settings()
    policy = next((p for p in sorted(policies, key=lambda p: p.priority)
                   if p.policy_type == PolicyType.REPEATED_ACTION and p.is_active), None)
    cfg = (policy.config if policy else {}) or {}
    return policy, {
        "threshold": int(cfg.get("threshold", s.default_repeat_threshold)),
        "window_seconds": int(cfg.get("window_seconds", s.default_repeat_window_seconds)),
        "block_seconds": int(cfg.get("block_seconds", s.default_repeat_block_seconds)),
    }


class EvaluationService:
    def __init__(self, session: AsyncSession, redis: Redis):
        self.session = session
        self.redis = redis
        self.settings = get_settings()
        self.actions = ActionRepository(session)
        self.approvals = ApprovalRepository(session)
        self.tools = ToolRepository(session)
        self.policies = PolicyRepository(session)
        self.audit = AuditService(session)
        self.limiter = RateLimiter(redis)
        self.repeat = RepeatTracker(redis)

    # ------------------------------------------------------------------ evaluate
    async def evaluate(self, api_key: ApiKey, agent: Agent, req: EvaluateRequest) -> EvalResult:
        if agent.status != AgentStatus.ACTIVE:
            raise Forbidden("Agent is disabled", code="AGENT_DISABLED")
        if req.agent_id != agent.slug:
            raise Forbidden("agent_id does not match the API key's agent", code="AGENT_MISMATCH")
        org_id, agent_pk = agent.organization_id, agent.id  # plain values survive a rollback (ORM attrs get expired)
        started = time.perf_counter()

        fp = fingerprint(f"{req.tool}|{req.environment}|{json.dumps(req.arguments, sort_keys=True, default=str)}")
        existing = await self.actions.get_by_external(org_id, agent.id, req.action_id)
        if existing:
            if existing.fingerprint != fp:
                raise Conflict("action_id was already used with a different payload", code="ACTION_ID_REUSED")
            if existing.reason_code not in TRANSIENT_REASONS:
                return await self._replay(existing)

        redacted_args, n_args = redact_value(req.arguments)
        redacted_reason, n_reason = redact_text(req.reason) if req.reason else (None, 0)

        policies = await self.policies.list_active(org_id)
        tool = await self.tools.get_by_name(org_id, req.tool)
        permitted = bool(tool and tool.is_active and await self.tools.is_assigned(agent.id, tool.id))
        ctx = ActionContext(
            agent_id=agent.slug, tool=req.tool, environment=req.environment, estimated_cost=float(req.estimated_cost),
            reason=req.reason, arguments=req.arguments, tool_known=tool is not None, tool_permitted=permitted,
        )

        try:
            result, status_code, headers, rl_event = await self._decide(ctx, policies, api_key, agent, fp)
        except RedisError as exc:  # fail closed: a governance gateway must not guess when its state store is down
            log.error("redis unavailable during evaluation", exc_info=True)
            raise ServiceUnavailable("Policy state store unavailable; action not authorised",
                                     code="STATE_STORE_UNAVAILABLE") from exc

        try:
            action, approval = await self._persist(
                existing, org_id, agent, api_key, req, fp, tool, redacted_args, redacted_reason,
                n_args + n_reason, result, int((time.perf_counter() - started) * 1000), rl_event,
            )
        except IntegrityError:
            # Two concurrent requests with the same action_id: the unique constraint picked a winner.
            await self.session.rollback()
            winner = await self.actions.get_by_external(org_id, agent_pk, req.action_id)
            if winner is None:
                raise
            return await self._replay(winner)

        await self._after_commit(action, approval, result, fp, policies, agent)
        body = build_body(req.action_id, result.decision, result.reason_code, result.message,
                          result.policy.id if result.policy else None, approval)
        if status_code == 200 and result.decision == Decision.REQUIRE_APPROVAL:
            status_code = 202
        return EvalResult(status_code, body, headers)

    async def _decide(self, ctx: ActionContext, policies: list[Policy], api_key: ApiKey, agent: Agent, fp: str):
        org_id = agent.organization_id
        repeat_policy, rcfg = repeat_config(policies)
        ttl = await self.repeat.blocked_ttl(org_id, agent.id, fp)
        if ttl > 0:
            res = EngineResult(
                Decision.BLOCK, "REPEATED_ACTION_BLOCKED",
                f"Identical action temporarily blocked for {ttl}s after repeated failures", repeat_policy,
                [{"step": "repeat_check", "blocked": True, "retry_after_seconds": ttl}],
            )
            return res, 200, {"Retry-After": str(ttl)}, None

        rl_policies = sorted((p for p in policies if p.policy_type == PolicyType.RATE_LIMIT), key=lambda p: p.priority)
        limits: list[tuple[Policy | None, str, int, int]] = []
        for p in rl_policies:
            cfg = p.config or {}
            limits.append((p, cfg.get("scope", "agent"), int(cfg.get("limit", 60)), int(cfg.get("window_seconds", 60))))
        if not limits:
            limits.append((None, "agent", self.settings.default_rate_limit_per_minute, 60))

        for policy, scope, limit, window in limits:
            scope_id = api_key.id if scope == "api_key" else agent.id
            key = redis_keys.rate_limit(scope, scope_id, str(policy.id) if policy else "default")
            allowed, count, retry = await self.limiter.hit(key, limit, window)
            if not allowed:
                res = EngineResult(
                    Decision.BLOCK, "RATE_LIMIT_EXCEEDED",
                    f"Rate limit exceeded: {limit} actions per {window}s per {scope}. Retry in {retry}s.", policy,
                    [{"step": "rate_limit", "scope": scope, "limit": limit, "window_seconds": window,
                      "observed": count, "retry_after_seconds": retry}],
                )
                event = RateLimitEvent(
                    organization_id=org_id, agent_id=agent.id, api_key_id=api_key.id,
                    policy_id=policy.id if policy else None, scope=scope, limit=limit, window_seconds=window,
                    observed=count,
                )
                return res, 429, {"Retry-After": str(retry)}, event

        return evaluate(ctx, policies), 200, {}, None

    async def _persist(self, existing, org_id, agent, api_key, req, fp, tool, redacted_args, redacted_reason,
                       n_redacted, result: EngineResult, latency_ms, rl_event):
        now = utcnow()
        status = STATUS_FOR[result.decision]
        if existing:
            action = existing
            action.decision, action.status, action.reason_code = result.decision, status, result.reason_code
            action.latency_ms, action.api_key_id = latency_ms, api_key.id
            decision_row = await self.actions.get_decision(action.id)
            if decision_row:
                decision_row.policy_id = result.policy.id if result.policy else None
                decision_row.decision, decision_row.reason_code = result.decision, result.reason_code
                decision_row.message, decision_row.trace = result.message, result.trace
        else:
            action = self.actions.add(ActionRequest(
                organization_id=org_id, agent_id=agent.id, api_key_id=api_key.id, action_id=req.action_id,
                tool=req.tool, environment=req.environment, arguments=redacted_args,
                estimated_cost=req.estimated_cost, reason=redacted_reason, fingerprint=fp,
                secrets_redacted=n_redacted, decision=result.decision, status=status,
                reason_code=result.reason_code, latency_ms=latency_ms,
            ))
            await self.session.flush()
            self.actions.add(PolicyDecision(
                organization_id=org_id, action_request_id=action.id, policy_id=result.policy.id if result.policy else None,
                decision=result.decision, reason_code=result.reason_code, message=result.message, trace=result.trace,
            ))

        approval = None
        if result.decision == Decision.REQUIRE_APPROVAL:
            ttl_min = result.approval_ttl_minutes or self.settings.approval_ttl_minutes
            approval = self.approvals.add(Approval(
                organization_id=org_id, action_request_id=action.id,
                policy_id=result.policy.id if result.policy else None, status=ApprovalStatus.PENDING,
                message=result.message, expires_at=now + timedelta(minutes=ttl_min),
            ))
        if rl_event:
            self.session.add(rl_event)

        if api_key.last_used_at is None or (now - api_key.last_used_at).total_seconds() > 60:
            api_key.last_used_at = now  # throttled to one write per minute to avoid hot-row contention
            self.session.add(api_key)

        await self.session.flush()
        await self.audit.log(
            org_id=org_id, actor_type=ActorType.AGENT, actor_id=agent.id, actor_label=agent.slug,
            event_type="ACTION_EVALUATED", entity_type="action_request", entity_id=action.id,
            details={
                "action_id": req.action_id, "tool": req.tool, "environment": req.environment,
                "decision": result.decision.value, "reason_code": result.reason_code,
                "policy_id": str(result.policy.id) if result.policy else None,
                "estimated_cost": str(req.estimated_cost), "secrets_redacted": n_redacted,
                "approval_id": str(approval.id) if approval else None,
            },
        )
        await self.session.commit()
        return action, approval

    async def _after_commit(self, action, approval, result: EngineResult, fp, policies, agent) -> None:
        try:
            if result.decision == Decision.BLOCK and result.reason_code not in TRANSIENT_REASONS:
                _, cfg = repeat_config(policies)
                await self.repeat.record_failure(action.organization_id, agent.id, fp, **cfg)
            if approval:
                await approval_service.publish_state(self.redis, approval, action.action_id)
            await bump_analytics_version(self.redis, action.organization_id)
        except RedisError:
            log.warning("post-commit redis side effects failed", exc_info=True)

    # ------------------------------------------------------------------ replay / status / outcome
    async def _replay(self, action: ActionRequest) -> EvalResult:
        pd = await self.actions.get_decision(action.id)
        approval = await self.approvals.get_for_action(action.id)
        body = build_body(action.action_id, action.decision, action.reason_code or "", pd.message if pd else None,
                          pd.policy_id if pd else None, approval)
        if action.decision == Decision.REQUIRE_APPROVAL:
            body["approval_status"] = approval.status.value if approval else None
        return EvalResult(202 if action.decision == Decision.REQUIRE_APPROVAL else 200, body, {"X-Idempotent-Replay": "true"})

    async def report_outcome(self, agent: Agent, action_id: str, req: OutcomeRequest) -> dict[str, Any]:
        action = await self.actions.get_by_external(agent.organization_id, agent.id, action_id)
        if not action:
            raise NotFound("Action not found", code="ACTION_NOT_FOUND")
        if action.status not in (ActionStatus.ALLOWED, ActionStatus.APPROVED):
            raise Conflict("Outcome can only be reported for allowed or approved actions", code="OUTCOME_NOT_ALLOWED")
        if action.outcome is not None:
            raise Conflict("Outcome already reported", code="OUTCOME_ALREADY_REPORTED")
        action.outcome = ActionOutcome(req.outcome)
        action.outcome_at = utcnow()
        await self.audit.log(
            org_id=agent.organization_id, actor_type=ActorType.AGENT, actor_id=agent.id, actor_label=agent.slug,
            event_type="ACTION_OUTCOME_REPORTED", entity_type="action_request", entity_id=action.id,
            details={"action_id": action_id, "outcome": req.outcome.value, "detail": redact_text(req.detail or "")[0]},
        )
        await self.session.commit()
        tripped = False
        if action.outcome == ActionOutcome.FAILED:
            try:
                policies = await self.policies.list_active(agent.organization_id)
                _, cfg = repeat_config(policies)
                tripped = await self.repeat.record_failure(agent.organization_id, agent.id, action.fingerprint, **cfg)
            except RedisError:
                log.warning("could not record failed outcome in redis", exc_info=True)
        return {"action_id": action_id, "outcome": req.outcome.value, "temporarily_blocked": tripped}
