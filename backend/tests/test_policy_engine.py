"""Pure unit tests for the policy engine - no DB, no Redis."""
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.models.enums import Decision, PolicyType, RuleOperator
from app.services.policy_engine import ActionContext, apply_operator, evaluate, resolve_field


@dataclass
class R:
    field: str
    operator: RuleOperator
    value: Any


@dataclass
class P:
    name: str
    effect: Decision
    rules: list[R]
    priority: int = 100
    policy_type: PolicyType = PolicyType.RULE
    is_active: bool = True
    reason_code: str = "CODE"
    message: str | None = None
    config: dict = field(default_factory=dict)
    id: Any = field(default_factory=uuid4)


def ctx(**kw) -> ActionContext:
    base = dict(agent_id="a", tool="delete_database_records", environment="production", estimated_cost=12.5,
                arguments={"table": "old_logs", "sql": "DROP TABLE users", "nested": {"limit": 5}})
    base.update(kw)
    return ActionContext(**base)


def test_default_allow_when_nothing_matches():
    r = evaluate(ctx(), [])
    assert r.decision == Decision.ALLOW and r.policy is None and r.reason_code == "NO_POLICY_MATCHED"


def test_block_beats_approval_beats_allow_regardless_of_priority():
    allow = P("allow", Decision.ALLOW, [R("tool", RuleOperator.EQ, "delete_database_records")], priority=1)
    appr = P("appr", Decision.REQUIRE_APPROVAL, [R("environment", RuleOperator.EQ, "production")], priority=2)
    block = P("block", Decision.BLOCK, [R("estimated_cost", RuleOperator.GT, 10)], priority=999)
    assert evaluate(ctx(), [allow, appr, block]).policy is block
    assert evaluate(ctx(), [allow, appr]).policy is appr
    assert evaluate(ctx(), [allow]).policy is allow


def test_lowest_priority_number_wins_within_same_effect():
    a = P("a", Decision.BLOCK, [R("tool", RuleOperator.EQ, "delete_database_records")], priority=50, reason_code="A")
    b = P("b", Decision.BLOCK, [R("tool", RuleOperator.EQ, "delete_database_records")], priority=5, reason_code="B")
    assert evaluate(ctx(), [a, b]).reason_code == "B"


def test_rules_inside_a_policy_are_anded():
    p = P("p", Decision.BLOCK, [R("tool", RuleOperator.EQ, "delete_database_records"),
                                R("environment", RuleOperator.EQ, "staging")])
    assert evaluate(ctx(environment="staging"), [p]).decision == Decision.BLOCK
    assert evaluate(ctx(environment="production"), [p]).decision == Decision.ALLOW


def test_inactive_policies_ignored_and_empty_rules_never_match():
    inactive = P("i", Decision.BLOCK, [R("tool", RuleOperator.EQ, "delete_database_records")], is_active=False)
    empty = P("e", Decision.BLOCK, [])
    assert evaluate(ctx(), [inactive, empty]).decision == Decision.ALLOW


def test_unknown_tool_and_unpermitted_tool_blocked():
    unknown = P("unknown", Decision.BLOCK, [], policy_type=PolicyType.UNKNOWN_TOOL, reason_code="UNKNOWN_TOOL",
                message="Unknown tools are blocked")
    r = evaluate(ctx(tool_known=False, tool_permitted=False), [unknown])
    assert r.decision == Decision.BLOCK and r.reason_code == "UNKNOWN_TOOL" and r.policy is unknown
    r = evaluate(ctx(tool_known=True, tool_permitted=False), [])
    assert r.decision == Decision.BLOCK and r.reason_code == "TOOL_NOT_PERMITTED"


def test_approval_ttl_comes_from_policy_config():
    p = P("p", Decision.REQUIRE_APPROVAL, [R("estimated_cost", RuleOperator.GTE, 10)], config={"ttl_minutes": 5})
    assert evaluate(ctx(), [p]).approval_ttl_minutes == 5


def test_operators():
    assert apply_operator(RuleOperator.EQ, "PRODUCTION", "production")
    assert apply_operator(RuleOperator.EQ, 10, "10.0")
    assert apply_operator(RuleOperator.IN, "send_email", ["Send_Email", "x"])
    assert apply_operator(RuleOperator.NOT_IN, "x", ["a", "b"])
    assert apply_operator(RuleOperator.GT, 10.01, 10) and not apply_operator(RuleOperator.GT, 10, 10)
    assert apply_operator(RuleOperator.GTE, 10, 10) and apply_operator(RuleOperator.LT, 1, 2)
    assert not apply_operator(RuleOperator.GT, "abc", 1)
    assert apply_operator(RuleOperator.CONTAINS, "Drop Table x", "drop table")
    assert apply_operator(RuleOperator.STARTSWITH, "delete_x", "DELETE")
    assert apply_operator(RuleOperator.REGEX, "please DROP   TABLE users", r"\bdrop\s+table\b")
    assert not apply_operator(RuleOperator.REGEX, "x", "(")  # invalid regex never matches (and never raises)
    assert not apply_operator(RuleOperator.EQ, None, "x") and apply_operator(RuleOperator.NEQ, None, "x")


def test_field_resolution_including_nested_arguments():
    c = ctx()
    assert resolve_field(c, "arguments.table") == "old_logs"
    assert resolve_field(c, "arguments.nested.limit") == 5
    assert resolve_field(c, "arguments.missing") is None
    assert "DROP TABLE" in resolve_field(c, "arguments_text")


def test_drop_table_regex_policy_and_trace():
    drop = P("drop", Decision.BLOCK, [R("arguments_text", RuleOperator.REGEX, r"\bDROP\s+TABLE\b")], priority=1)
    other = P("other", Decision.BLOCK, [R("tool", RuleOperator.EQ, "nothing")], priority=2)
    r = evaluate(ctx(), [other, drop])
    assert r.policy is drop
    matched = {t["name"]: t["matched"] for t in r.trace if t["step"] == "policy"}
    assert matched == {"drop": True, "other": False}
