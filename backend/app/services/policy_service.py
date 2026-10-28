import re
import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.models import Policy, PolicyRule
from app.models.enums import ActorType, Decision, PolicyType, RuleOperator
from app.repositories.agents import AgentRepository, ToolRepository
from app.repositories.policies import PolicyRepository
from app.schemas.policies import PolicyCreate, PolicyUpdate, RuleIn, SimulateRequest, SimulateResponse
from app.services.audit_service import AuditService
from app.services.cache import bump_analytics_version
from app.services.policy_engine import MAX_REGEX_LEN, ActionContext, evaluate, is_valid_field
from app.services.principal import Principal

NUMERIC_OPS = {RuleOperator.GT, RuleOperator.GTE, RuleOperator.LT, RuleOperator.LTE}


def _int_in(cfg: dict, key: str, lo: int, hi: int, default: int | None = None) -> int:
    val = cfg.get(key, default)
    if isinstance(val, bool) or not isinstance(val, int) or not (lo <= val <= hi):
        raise ValidationFailed(f"config.{key} must be an integer between {lo} and {hi}", code="INVALID_POLICY_CONFIG")
    return val


def validate_rule(rule: RuleIn) -> None:
    if not is_valid_field(rule.field):
        raise ValidationFailed(f"Unknown rule field '{rule.field}'", code="INVALID_RULE_FIELD")
    op, val = rule.operator, rule.value
    if op in (RuleOperator.IN, RuleOperator.NOT_IN) and not (isinstance(val, list) and val):
        raise ValidationFailed(f"Operator '{op.value}' needs a non-empty list value", code="INVALID_RULE_VALUE")
    if op in NUMERIC_OPS and (isinstance(val, bool) or not isinstance(val, (int, float))):
        raise ValidationFailed(f"Operator '{op.value}' needs a numeric value", code="INVALID_RULE_VALUE")
    if op == RuleOperator.REGEX:
        if not isinstance(val, str) or not val or len(val) > MAX_REGEX_LEN:
            raise ValidationFailed(f"Regex must be a string of at most {MAX_REGEX_LEN} characters", code="INVALID_RULE_VALUE")
        try:
            re.compile(val)
        except re.error as exc:
            raise ValidationFailed(f"Invalid regex: {exc}", code="INVALID_RULE_VALUE") from exc
    if op in (RuleOperator.CONTAINS, RuleOperator.NOT_CONTAINS, RuleOperator.STARTSWITH) and not isinstance(val, (str, int, float)):
        raise ValidationFailed(f"Operator '{op.value}' needs a scalar value", code="INVALID_RULE_VALUE")


def validate_policy(policy_type: PolicyType, effect: Decision, config: dict[str, Any], rules: list[RuleIn]) -> tuple[Decision, dict[str, Any]]:
    """Returns the normalised (effect, config). Raises ValidationFailed for inconsistent policies."""
    if policy_type == PolicyType.RULE:
        if not rules:
            raise ValidationFailed("RULE policies need at least one rule", code="RULES_REQUIRED")
        for r in rules:
            validate_rule(r)
        clean: dict[str, Any] = {}
        if effect == Decision.REQUIRE_APPROVAL and "ttl_minutes" in config:
            clean["ttl_minutes"] = _int_in(config, "ttl_minutes", 1, 10080)
        return effect, clean
    if rules:
        raise ValidationFailed(f"{policy_type.value} policies do not take rules", code="RULES_NOT_ALLOWED")
    if policy_type == PolicyType.RATE_LIMIT:
        scope = config.get("scope", "agent")
        if scope not in ("agent", "api_key"):
            raise ValidationFailed("config.scope must be 'agent' or 'api_key'", code="INVALID_POLICY_CONFIG")
        return Decision.BLOCK, {"limit": _int_in(config, "limit", 1, 1_000_000), "scope": scope,
                                "window_seconds": _int_in(config, "window_seconds", 1, 86400, 60)}
    if policy_type == PolicyType.REPEATED_ACTION:
        return Decision.BLOCK, {"threshold": _int_in(config, "threshold", 1, 1000, 3),
                                "window_seconds": _int_in(config, "window_seconds", 1, 86400, 600),
                                "block_seconds": _int_in(config, "block_seconds", 1, 86400, 300)}
    return Decision.BLOCK, {}  # UNKNOWN_TOOL


def _make_rules(rules: list[RuleIn]) -> list[PolicyRule]:
    return [PolicyRule(position=i, field=r.field, operator=r.operator, value=r.value) for i, r in enumerate(rules)]


class PolicyService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.redis = redis
        self.policies = PolicyRepository(session)
        self.audit = AuditService(session)

    def _actor(self, p: Principal) -> dict[str, Any]:
        return {"actor_type": ActorType.USER, "actor_id": p.user_id, "actor_label": p.email}

    async def get(self, p: Principal, policy_id: uuid.UUID) -> Policy:
        policy = await self.policies.get(p.org_id, policy_id)
        if not policy:
            raise NotFound("Policy not found", code="POLICY_NOT_FOUND")
        return policy

    async def create(self, p: Principal, data: PolicyCreate) -> Policy:
        if await self.policies.get_by_name(p.org_id, data.name):
            raise Conflict("A policy with this name already exists", code="POLICY_NAME_TAKEN")
        effect, config = validate_policy(data.policy_type, data.effect, data.config, data.rules)
        policy = self.policies.add(Policy(
            organization_id=p.org_id, name=data.name, description=data.description, policy_type=data.policy_type,
            effect=effect, priority=data.priority, is_active=data.is_active, reason_code=data.reason_code,
            message=data.message, config=config, rules=_make_rules(data.rules),
        ))
        await self.session.flush()
        await self.audit.log(org_id=p.org_id, event_type="POLICY_CREATED", entity_type="policy", entity_id=policy.id,
                             details={"name": policy.name, "type": policy.policy_type.value,
                                      "effect": policy.effect.value, "priority": policy.priority}, **self._actor(p))
        await self.session.commit()
        return policy

    async def update(self, p: Principal, policy_id: uuid.UUID, data: PolicyUpdate) -> Policy:
        policy = await self.get(p, policy_id)
        changes = data.model_dump(exclude_unset=True, exclude={"rules", "config"})
        if "name" in changes and changes["name"] != policy.name and await self.policies.get_by_name(p.org_id, changes["name"]):
            raise Conflict("A policy with this name already exists", code="POLICY_NAME_TAKEN")
        new_rules = data.rules if data.rules is not None else [
            RuleIn(field=r.field, operator=r.operator, value=r.value) for r in policy.rules]
        effect, config = validate_policy(
            policy.policy_type, data.effect or policy.effect,
            data.config if data.config is not None else policy.config, new_rules)
        for k, v in changes.items():
            setattr(policy, k, v)
        policy.effect, policy.config = effect, config
        if data.rules is not None:
            policy.rules.clear()
            await self.session.flush()
            policy.rules.extend(_make_rules(data.rules))
        await self.audit.log(org_id=p.org_id, event_type="POLICY_UPDATED", entity_type="policy", entity_id=policy.id,
                             details={"name": policy.name, "changed": sorted(data.model_dump(exclude_unset=True))},
                             **self._actor(p))
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def delete(self, p: Principal, policy_id: uuid.UUID) -> None:
        policy = await self.get(p, policy_id)
        name = policy.name
        await self.policies.delete(policy)
        await self.audit.log(org_id=p.org_id, event_type="POLICY_DELETED", entity_type="policy", entity_id=policy_id,
                             details={"name": name}, **self._actor(p))
        await self.session.commit()

    async def simulate(self, p: Principal, data: SimulateRequest) -> SimulateResponse:
        agent = await AgentRepository(self.session).get_by_slug(p.org_id, data.agent_id)
        tool = await ToolRepository(self.session).get_by_name(p.org_id, data.tool)
        permitted = bool(agent and tool and tool.is_active and await ToolRepository(self.session).is_assigned(agent.id, tool.id))
        ctx = ActionContext(agent_id=data.agent_id, tool=data.tool, environment=data.environment.lower(),
                            estimated_cost=data.estimated_cost, reason=data.reason, arguments=data.arguments,
                            tool_known=tool is not None, tool_permitted=permitted)
        result = evaluate(ctx, await self.policies.list_active(p.org_id))
        return SimulateResponse(
            decision=result.decision, reason_code=result.reason_code, message=result.message,
            policy_id=result.policy.id if result.policy else None,
            policy_name=result.policy.name if result.policy else None,
            tool_known=tool is not None, tool_permitted=permitted, trace=result.trace,
        )
