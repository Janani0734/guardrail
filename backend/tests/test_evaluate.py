import asyncio

from sqlalchemy import select

from app.models import ActionRequest, PolicyDecision, RateLimitEvent
from tests.conftest import evaluate, make_policy


async def test_allow_when_no_policy_matches(client, world):
    r = await evaluate(client, world, action_id="act_allow_1")
    assert r.status_code == 200
    body = r.json()
    assert body == {"decision": "ALLOW", "action_id": "act_allow_1", "policy_id": None, "expires_at": None}


async def test_explicit_allow_policy_reports_policy_id(client, world):
    pol = await make_policy(client, world["admin"], effect="ALLOW", rules=[{"field": "tool", "operator": "eq", "value": "read_logs"}])
    r = await evaluate(client, world)
    assert r.json()["decision"] == "ALLOW" and r.json()["policy_id"] == pol["id"]


async def test_block_tool_in_production_matches_spec_example(client, world):
    pol = await make_policy(
        client, world["admin"], name="Block delete in prod", effect="BLOCK", priority=20,
        reason_code="FORBIDDEN_TOOL_IN_PRODUCTION", message="Tool delete_database_records is blocked in production",
        rules=[{"field": "tool", "operator": "eq", "value": "delete_database_records"},
               {"field": "environment", "operator": "eq", "value": "production"}])
    r = await evaluate(client, world, action_id="act_123", tool="delete_database_records", environment="production",
                       arguments={"table": "old_logs", "limit": 1000}, estimated_cost=12.5,
                       reason="Clean expired log records")
    assert r.status_code == 200
    assert r.json() == {"decision": "BLOCK", "action_id": "act_123", "reason_code": "FORBIDDEN_TOOL_IN_PRODUCTION",
                        "message": "Tool delete_database_records is blocked in production", "policy_id": pol["id"]}
    # same tool in staging is not caught by that policy
    assert (await evaluate(client, world, tool="delete_database_records", environment="staging")).json()["decision"] == "ALLOW"


async def test_global_tool_block(client, world):
    await make_policy(client, world["admin"], rules=[{"field": "tool", "operator": "eq", "value": "send_email"}],
                      reason_code="TOOL_BANNED")
    for env in ("production", "staging", "dev"):
        r = await evaluate(client, world, tool="send_email", environment=env)
        assert r.json()["decision"] == "BLOCK" and r.json()["reason_code"] == "TOOL_BANNED"


async def test_drop_table_always_blocked(client, world):
    await make_policy(client, world["admin"], priority=1, reason_code="DROP_TABLE_FORBIDDEN",
                      rules=[{"field": "arguments_text", "operator": "regex", "value": "\\bDROP\\s+TABLE\\b"}])
    r = await evaluate(client, world, arguments={"sql": "drop   table users;"}, environment="dev")
    assert r.json()["decision"] == "BLOCK" and r.json()["reason_code"] == "DROP_TABLE_FORBIDDEN"


async def test_cost_threshold_requires_approval(client, world):
    await make_policy(client, world["admin"], effect="REQUIRE_APPROVAL", reason_code="HIGH_COST",
                      message="High-cost production action requires admin approval",
                      rules=[{"field": "estimated_cost", "operator": "gt", "value": 10}])
    low = await evaluate(client, world, estimated_cost=10)
    high = await evaluate(client, world, estimated_cost=10.01)
    assert low.json()["decision"] == "ALLOW"
    assert high.status_code == 202
    body = high.json()
    assert body["decision"] == "REQUIRE_APPROVAL" and body["approval_id"] and body["expires_at"].endswith("Z")
    assert body["message"] == "High-cost production action requires admin approval"


async def test_delete_in_production_requires_approval_but_not_in_staging(client, world):
    await make_policy(client, world["admin"], effect="REQUIRE_APPROVAL", rules=[
        {"field": "environment", "operator": "eq", "value": "production"},
        {"field": "arguments_text", "operator": "regex", "value": "\\b(DELETE|DROP|TRUNCATE)\\b"}])
    assert (await evaluate(client, world, environment="production", arguments={"sql": "DELETE FROM t"})).status_code == 202
    assert (await evaluate(client, world, environment="staging", arguments={"sql": "DELETE FROM t"})).status_code == 200


async def test_unknown_tool_blocked(client, world):
    r = await evaluate(client, world, tool="launch_missiles")
    assert r.json()["decision"] == "BLOCK" and r.json()["reason_code"] == "UNKNOWN_TOOL"


async def test_unknown_tool_policy_customises_message_and_policy_id(client, world):
    pol = await make_policy(client, world["admin"], name="Block unknown tools", policy_type="UNKNOWN_TOOL",
                            reason_code="UNKNOWN_TOOL", message="Unregistered tools are not allowed")
    r = (await evaluate(client, world, tool="launch_missiles")).json()
    assert r["policy_id"] == pol["id"] and r["message"] == "Unregistered tools are not allowed"


async def test_registered_but_unassigned_tool_blocked(client, world):
    await client.post("/v1/tools", headers=world["admin"], json={"name": "wire_transfer", "risk_level": "CRITICAL"})
    r = (await evaluate(client, world, tool="wire_transfer")).json()
    assert r["decision"] == "BLOCK" and r["reason_code"] == "TOOL_NOT_PERMITTED"


async def test_inactive_tool_blocked(client, world):
    await client.patch(f"/v1/tools/{world['tool_ids'][0]}", headers=world["admin"], json={"is_active": False})
    assert (await evaluate(client, world, tool="read_logs")).json()["reason_code"] == "TOOL_NOT_PERMITTED"


async def test_every_evaluation_is_persisted_with_decision_and_audit(client, world, sessionmaker):
    await make_policy(client, world["admin"], rules=[{"field": "tool", "operator": "eq", "value": "send_email"}])
    await evaluate(client, world, tool="send_email")
    await evaluate(client, world, tool="read_logs")
    async with sessionmaker() as s:
        actions = (await s.execute(select(ActionRequest))).scalars().all()
        decisions = (await s.execute(select(PolicyDecision))).scalars().all()
    assert len(actions) == len(decisions) == 2
    assert {d.decision.value for d in decisions} == {"BLOCK", "ALLOW"}
    audit = (await client.get("/v1/audit-logs?event_type=ACTION_EVALUATED", headers=world["admin"])).json()
    assert audit["total"] == 2


async def test_idempotent_replay_returns_same_decision_without_duplicate_rows(client, world, sessionmaker):
    await make_policy(client, world["admin"], effect="REQUIRE_APPROVAL",
                      rules=[{"field": "estimated_cost", "operator": "gt", "value": 5}])
    first = await evaluate(client, world, action_id="same", estimated_cost=50)
    second = await evaluate(client, world, action_id="same", estimated_cost=50)
    assert first.status_code == second.status_code == 202
    assert first.json()["approval_id"] == second.json()["approval_id"]
    assert second.headers.get("x-idempotent-replay") == "true"
    async with sessionmaker() as s:
        assert len((await s.execute(select(ActionRequest))).scalars().all()) == 1


async def test_action_id_reuse_with_different_payload_conflicts(client, world):
    await evaluate(client, world, action_id="dup", tool="read_logs")
    r = await evaluate(client, world, action_id="dup", tool="send_email")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTION_ID_REUSED"


async def test_concurrent_identical_requests_create_one_action(client, world, sessionmaker):
    rs = await asyncio.gather(*[evaluate(client, world, action_id="race") for _ in range(5)])
    assert all(r.status_code == 200 for r in rs)
    async with sessionmaker() as s:
        assert len((await s.execute(select(ActionRequest))).scalars().all()) == 1


async def test_validation_errors(client, world):
    assert (await evaluate(client, world, estimated_cost=-1)).status_code == 422
    assert (await evaluate(client, world, environment="prod uction")).status_code == 422
    assert (await evaluate(client, world, tool="")).status_code == 422
    assert (await evaluate(client, world, arguments={"blob": "x" * 70000})).status_code == 422


# ------------------------------------------------------------------ rate limiting
async def test_rate_limit_policy_returns_429_with_retry_after(client, world, sessionmaker):
    await make_policy(client, world["admin"], name="3 per minute", policy_type="RATE_LIMIT",
                      config={"limit": 3, "window_seconds": 60, "scope": "agent"}, reason_code="RATE_LIMIT_EXCEEDED")
    codes = [(await evaluate(client, world)).status_code for _ in range(3)]
    assert codes == [200, 200, 200]
    r = await evaluate(client, world)
    assert r.status_code == 429
    assert r.json()["decision"] == "BLOCK" and r.json()["reason_code"] == "RATE_LIMIT_EXCEEDED"
    assert 1 <= int(r.headers["retry-after"]) <= 60
    async with sessionmaker() as s:
        events = (await s.execute(select(RateLimitEvent))).scalars().all()
    assert len(events) == 1 and events[0].limit == 3 and events[0].scope == "agent"


async def test_default_rate_limit_applies_without_a_policy(client, world, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "default_rate_limit_per_minute", 2)
    assert [(await evaluate(client, world)).status_code for _ in range(3)] == [200, 200, 429]


async def test_rate_limit_is_per_api_key_when_scoped_that_way(client, world):
    await make_policy(client, world["admin"], policy_type="RATE_LIMIT", config={"limit": 1, "scope": "api_key"})
    second_key = (await client.post(f"/v1/agents/{world['agent']['id']}/api-keys", headers=world["admin"],
                                    json={"name": "second"})).json()["key"]
    assert (await evaluate(client, world)).status_code == 200
    assert (await evaluate(client, world)).status_code == 429
    other = dict(world, key=second_key)
    assert (await evaluate(client, other)).status_code == 200  # a different key has its own budget


async def test_rate_limited_action_can_be_retried_with_same_action_id(client, world, redis):
    await make_policy(client, world["admin"], policy_type="RATE_LIMIT", config={"limit": 1, "window_seconds": 60})
    assert (await evaluate(client, world, action_id="first")).status_code == 200
    assert (await evaluate(client, world, action_id="retry-me")).status_code == 429
    await redis.flushall()  # window elapsed
    r = await evaluate(client, world, action_id="retry-me")
    assert r.status_code == 200 and r.json()["decision"] == "ALLOW"


# ------------------------------------------------------------------ repeated failures
async def test_repeated_blocked_action_is_temporarily_blocked(client, world):
    await make_policy(client, world["admin"], name="ban email", rules=[{"field": "tool", "operator": "eq", "value": "send_email"}],
                      reason_code="TOOL_BANNED", priority=5)
    await make_policy(client, world["admin"], name="repeat guard", policy_type="REPEATED_ACTION",
                      config={"threshold": 3, "window_seconds": 600, "block_seconds": 300})
    args = {"to": "ceo@example.com"}
    codes = [(await evaluate(client, world, tool="send_email", arguments=args)).json()["reason_code"] for _ in range(3)]
    assert codes == ["TOOL_BANNED"] * 3
    r = await evaluate(client, world, tool="send_email", arguments=args)
    assert r.json()["reason_code"] == "REPEATED_ACTION_BLOCKED" and int(r.headers["retry-after"]) > 0
    # a different payload is a different fingerprint
    other = await evaluate(client, world, tool="send_email", arguments={"to": "someone-else@example.com"})
    assert other.json()["reason_code"] == "TOOL_BANNED"


async def test_repeated_failed_outcomes_trip_the_block(client, world):
    await make_policy(client, world["admin"], policy_type="REPEATED_ACTION", config={"threshold": 3})
    key = {"X-API-Key": world["key"]}
    for i in range(3):
        r = await evaluate(client, world, action_id=f"flaky-{i}", arguments={"job": "nightly"})
        assert r.json()["decision"] == "ALLOW"
        o = await client.post(f"/v1/actions/flaky-{i}/outcome", headers=key, json={"outcome": "FAILED"})
        assert o.status_code == 200
    assert o.json()["temporarily_blocked"] is True
    r = await evaluate(client, world, action_id="flaky-3", arguments={"job": "nightly"})
    assert r.json()["decision"] == "BLOCK" and r.json()["reason_code"] == "REPEATED_ACTION_BLOCKED"


async def test_outcome_rules(client, world):
    key = {"X-API-Key": world["key"]}
    assert (await client.post("/v1/actions/ghost/outcome", headers=key, json={"outcome": "SUCCEEDED"})).status_code == 404
    await make_policy(client, world["admin"], rules=[{"field": "tool", "operator": "eq", "value": "send_email"}])
    await evaluate(client, world, action_id="blocked-one", tool="send_email")
    r = await client.post("/v1/actions/blocked-one/outcome", headers=key, json={"outcome": "SUCCEEDED"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "OUTCOME_NOT_ALLOWED"
    await evaluate(client, world, action_id="ok-one")
    assert (await client.post("/v1/actions/ok-one/outcome", headers=key, json={"outcome": "SUCCEEDED"})).status_code == 200
    assert (await client.post("/v1/actions/ok-one/outcome", headers=key, json={"outcome": "SUCCEEDED"})).status_code == 409


# ------------------------------------------------------------------ secrets
async def test_secrets_are_redacted_before_persistence(client, world, sessionmaker):
    r = await evaluate(client, world, action_id="secret-1", arguments={
        "password": "hunter2hunter2", "note": "use AKIAIOSFODNN7EXAMPLE for s3",
        "headers": {"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz123456"}},
        reason="deploy with token=ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert r.status_code == 200
    async with sessionmaker() as s:
        action = (await s.execute(select(ActionRequest))).scalar_one()
    blob = str(action.arguments) + (action.reason or "")
    for leaked in ("hunter2hunter2", "AKIAIOSFODNN7EXAMPLE", "abcdefghijklmnopqrstuvwxyz123456", "ghp_abcdef"):
        assert leaked not in blob
    assert action.secrets_redacted >= 4 and "[REDACTED]" in blob
    history = await client.get("/v1/action-history", headers=world["viewer"])
    assert "hunter2hunter2" not in history.text
    audit = await client.get("/v1/audit-logs", headers=world["viewer"])
    assert "hunter2hunter2" not in audit.text


async def test_policies_still_match_on_unredacted_arguments(client, world):
    await make_policy(client, world["admin"], rules=[{"field": "arguments.password", "operator": "eq", "value": "hunter2hunter2"}],
                      reason_code="MATCHED_RAW")
    r = await evaluate(client, world, arguments={"password": "hunter2hunter2"})
    assert r.json()["reason_code"] == "MATCHED_RAW"


# ------------------------------------------------------------------ simulation
async def test_simulation_is_side_effect_free(client, world, sessionmaker):
    await make_policy(client, world["admin"], name="expensive", effect="REQUIRE_APPROVAL",
                      rules=[{"field": "estimated_cost", "operator": "gt", "value": 10}])
    r = await client.post("/v1/policies/simulate", headers=world["viewer"], json={
        "agent_id": "support-agent-01", "tool": "read_logs", "environment": "production", "estimated_cost": 99})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "REQUIRE_APPROVAL" and body["policy_name"] == "expensive" and body["trace"]
    async with sessionmaker() as s:
        assert (await s.execute(select(ActionRequest))).first() is None


async def test_fail_closed_when_redis_is_down(client, world, redis, monkeypatch):
    from redis.exceptions import ConnectionError as RedisConnectionError

    async def boom(*_, **__):
        raise RedisConnectionError("down")

    monkeypatch.setattr(redis, "ttl", boom)
    r = await evaluate(client, world)
    assert r.status_code == 503 and r.json()["error"]["code"] == "STATE_STORE_UNAVAILABLE"
