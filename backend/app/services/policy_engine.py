"""Pure, I/O-free policy engine.

Takes an ActionContext and the organisation's active policies and returns a decision plus a full trace.
Being pure makes it trivially unit-testable and reusable for the /policies/simulate endpoint and the seed script.

Precedence: BLOCK > REQUIRE_APPROVAL > explicit ALLOW > default ALLOW. Inside the same effect the policy with the
lowest `priority` number wins (ties broken by creation order, which is how policies are loaded).
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.enums import Decision, PolicyType, RuleOperator

VALID_FIELDS = {"tool", "environment", "estimated_cost", "reason", "agent_id", "arguments_text"}
MAX_REGEX_LEN = 300


@dataclass(frozen=True)
class ActionContext:
    agent_id: str
    tool: str
    environment: str
    estimated_cost: float = 0.0
    reason: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    tool_known: bool = True
    tool_permitted: bool = True


class RuleLike(Protocol):
    field: str
    operator: RuleOperator
    value: Any


@dataclass
class EngineResult:
    decision: Decision
    reason_code: str
    message: str | None
    policy: Any | None
    trace: list[dict[str, Any]]
    approval_ttl_minutes: int | None = None


def is_valid_field(name: str) -> bool:
    return name in VALID_FIELDS or (name.startswith("arguments.") and len(name) > len("arguments."))


def resolve_field(ctx: ActionContext, name: str) -> Any:
    if name == "tool":
        return ctx.tool
    if name == "environment":
        return ctx.environment
    if name == "estimated_cost":
        return ctx.estimated_cost
    if name == "reason":
        return ctx.reason
    if name == "agent_id":
        return ctx.agent_id
    if name == "arguments_text":
        return json.dumps(ctx.arguments, sort_keys=True, default=str)
    if name.startswith("arguments."):
        cur: Any = ctx.arguments
        for part in name.split(".")[1:]:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur
    return None


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _eq(a: Any, b: Any) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None and not (isinstance(a, str) and isinstance(b, str)):
        return na == nb
    return str(a).lower() == str(b).lower()


def apply_operator(op: RuleOperator, actual: Any, expected: Any) -> bool:
    if actual is None:
        return op in (RuleOperator.NEQ, RuleOperator.NOT_IN, RuleOperator.NOT_CONTAINS)
    if op in (RuleOperator.GT, RuleOperator.GTE, RuleOperator.LT, RuleOperator.LTE):
        a, e = _num(actual), _num(expected)
        if a is None or e is None:
            return False
        return {RuleOperator.GT: a > e, RuleOperator.GTE: a >= e, RuleOperator.LT: a < e, RuleOperator.LTE: a <= e}[op]
    if op == RuleOperator.EQ:
        return _eq(actual, expected)
    if op == RuleOperator.NEQ:
        return not _eq(actual, expected)
    if op in (RuleOperator.IN, RuleOperator.NOT_IN):
        options = expected if isinstance(expected, list) else [expected]
        hit = any(_eq(actual, o) for o in options)
        return hit if op == RuleOperator.IN else not hit
    if op == RuleOperator.CONTAINS:
        return str(expected).lower() in str(actual).lower()
    if op == RuleOperator.NOT_CONTAINS:
        return str(expected).lower() not in str(actual).lower()
    if op == RuleOperator.STARTSWITH:
        return str(actual).lower().startswith(str(expected).lower())
    if op == RuleOperator.REGEX:
        pattern = str(expected)
        if len(pattern) > MAX_REGEX_LEN:
            return False
        try:
            return re.search(pattern, str(actual), re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def rule_matches(ctx: ActionContext, rule: RuleLike) -> bool:
    return apply_operator(rule.operator, resolve_field(ctx, rule.field), rule.value)


def policy_matches(ctx: ActionContext, policy: Any) -> bool:
    rules = list(policy.rules)
    return bool(rules) and all(rule_matches(ctx, r) for r in rules)  # rules inside a policy are ANDed


def _default_message(policy: Any, decision: Decision) -> str:
    if policy.message:
        return policy.message
    if decision == Decision.BLOCK:
        return f"Blocked by policy '{policy.name}'"
    if decision == Decision.REQUIRE_APPROVAL:
        return f"Policy '{policy.name}' requires admin approval"
    return f"Allowed by policy '{policy.name}'"


def evaluate(ctx: ActionContext, policies: list[Any]) -> EngineResult:
    active = sorted((p for p in policies if p.is_active), key=lambda p: p.priority)
    trace: list[dict[str, Any]] = []

    if not ctx.tool_permitted:
        unknown = next((p for p in active if p.policy_type == PolicyType.UNKNOWN_TOOL), None)
        if not ctx.tool_known:
            code = unknown.reason_code if unknown else "UNKNOWN_TOOL"
            msg = (unknown.message if unknown and unknown.message else f"Tool {ctx.tool} is not registered")
        else:
            code = "TOOL_NOT_PERMITTED"
            msg = f"Tool {ctx.tool} is not permitted for agent {ctx.agent_id}"
        trace.append({"step": "tool_check", "tool_known": ctx.tool_known, "tool_permitted": False,
                      "policy_id": str(unknown.id) if unknown else None})
        return EngineResult(Decision.BLOCK, code, msg, unknown, trace)

    trace.append({"step": "tool_check", "tool_known": True, "tool_permitted": True})
    matches: list[Any] = []
    for p in active:
        if p.policy_type != PolicyType.RULE:
            continue
        hit = policy_matches(ctx, p)
        trace.append({"step": "policy", "policy_id": str(p.id), "name": p.name, "effect": p.effect.value,
                      "priority": p.priority, "matched": hit})
        if hit:
            matches.append(p)

    for effect in (Decision.BLOCK, Decision.REQUIRE_APPROVAL, Decision.ALLOW):
        winner = next((p for p in matches if p.effect == effect), None)
        if winner:
            ttl = None
            if effect == Decision.REQUIRE_APPROVAL:
                raw = (winner.config or {}).get("ttl_minutes")
                ttl = int(raw) if isinstance(raw, (int, float)) and raw > 0 else None
            return EngineResult(effect, winner.reason_code, _default_message(winner, effect), winner, trace, ttl)

    return EngineResult(Decision.ALLOW, "NO_POLICY_MATCHED", "No policy matched; default allow for permitted tool",
                        None, trace)
