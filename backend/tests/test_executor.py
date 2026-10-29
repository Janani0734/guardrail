"""Trusted Executor: AI agent -> Executor -> GuardRail -> run / refuse. Everything runs in-process (ASGI + fakeredis)."""
import asyncio
import uuid

import httpx
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app  # noqa: F401  (GuardRail app is the `client` fixture's)
from executor.config import ExecutorSettings
from executor.main import create_app as create_executor_app
from tests.conftest import make_policy


@pytest_asyncio.fixture
async def ex(client, world, redis):
    """An Executor wired to the in-process GuardRail (the `client` fixture), with its own fake Redis."""
    settings = ExecutorSettings(poll_interval_seconds=0.05, default_wait_seconds=0)
    import executor.main as m
    m.get_settings = lambda: settings
    app = create_executor_app(guardrail_http=client, redis=redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://executor") as c:
        yield c


def call(ex, world, tool="read_logs", args=None, action_id=None, env="staging", key=None, **extra):
    body = {"agent_id": "support-agent-01", "action_id": action_id or f"act_{uuid.uuid4().hex[:10]}", "tool": tool,
            "environment": env, "arguments": args if args is not None else {}, **extra}
    return ex.post("/v1/execute", headers={"X-API-Key": key or world["key"]}, json=body), body


async def run(ex, world, **kw):
    r, body = call(ex, world, **kw)
    return await r, body


async def require_approval(client, world):
    if world.get("_approval_policy"):
        return
    world["_approval_policy"] = True
    await make_policy(client, world["admin"], name="approve-email", effect="REQUIRE_APPROVAL", reason_code="NEEDS_APPROVAL",
                      rules=[{"field": "tool", "operator": "eq", "value": "send_email"}])


MAIL = {"to": "boss@example.com", "subject": "Hi", "body": "hello"}


async def test_allow_runs_the_fake_tool(ex, world):
    r, _ = await run(ex, world, tool="read_logs", args={"service": "api", "lines": 2})
    assert r.status_code == 200
    b = r.json()
    assert b["executed"] is True and b["decision"] == "ALLOW" and b["result"]["simulated"] is True
    assert len(b["result"]["lines"]) == 2


async def test_all_three_fake_tools_only_simulate(ex, world):
    r, _ = await run(ex, world, tool="send_email", args=MAIL)
    assert r.json()["result"]["note"].startswith("No email was sent")
    assert "hello" not in r.text  # the body is never echoed
    r, _ = await run(ex, world, tool="delete_database_records", args={"table": "old_logs", "limit": 5})
    assert r.json()["result"]["records_deleted"] == 0 and r.json()["result"]["simulated"] is True


async def test_block_is_refused(ex, client, world):
    await make_policy(client, world["admin"], name="no-prod-delete", effect="BLOCK", reason_code="NO_PROD_DELETE",
                      rules=[{"field": "tool", "operator": "eq", "value": "delete_database_records"}])
    r, _ = await run(ex, world, tool="delete_database_records", args={"table": "users", "limit": 10}, env="production")
    assert r.status_code == 403
    assert r.json()["executed"] is False and r.json()["reason_code"] == "NO_PROD_DELETE"


async def test_invalid_arguments_and_unknown_tool_never_reach_guardrail(ex, world):
    r, _ = await run(ex, world, tool="send_email", args={"to": "not-an-email"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOOL_ARGUMENTS_INVALID"
    r, _ = await run(ex, world, tool="issue_refund", args={})
    assert r.status_code == 501


async def test_missing_api_key_and_bad_key(ex, world):
    r = await ex.post("/v1/execute", json={"agent_id": "a", "action_id": "act_1", "tool": "read_logs",
                                           "environment": "staging", "arguments": {}})
    assert r.status_code == 401
    r, _ = await run(ex, world, key="grk_wrong_key_value")
    assert r.status_code in (401, 403) and r.json()["executed"] is False


async def test_approval_flow_runs_only_after_admin_approves(ex, client, world):
    await require_approval(client, world)
    aid = "act_mail_1"
    r, _ = await run(ex, world, tool="send_email", args=MAIL, action_id=aid)
    assert r.status_code == 202 and r.json()["status"] == "PENDING_APPROVAL" and r.json()["executed"] is False

    approvals = (await client.get("/v1/approvals?status=PENDING", headers=world["admin"])).json()["items"]
    ap = await client.post(f"/v1/approvals/{approvals[0]['id']}/approve", headers=world["admin"], json={})
    assert ap.status_code == 200

    r, _ = await run(ex, world, tool="send_email", args=MAIL, action_id=aid)
    assert r.status_code == 200
    assert r.json()["executed"] is True and r.json()["approved_by_human"] is True


async def test_waiting_call_returns_once_admin_approves(ex, client, world):
    await require_approval(client, world)

    async def approve_soon():
        for _ in range(100):
            await asyncio.sleep(0.1)
            items = (await client.get("/v1/approvals?status=PENDING", headers=world["admin"])).json()["items"]
            if items:
                await client.post(f"/v1/approvals/{items[0]['id']}/approve", headers=world["admin"], json={})
                return
    task = asyncio.create_task(approve_soon())
    r, _ = await run(ex, world, tool="send_email", args=MAIL, wait_seconds=10)
    await task
    assert r.status_code == 200 and r.json()["executed"] is True


async def test_rejected_approval_is_refused(ex, client, world):
    await require_approval(client, world)
    r, _ = await run(ex, world, tool="send_email", args=MAIL, action_id="act_rej")
    ap = (await client.get("/v1/approvals?status=PENDING", headers=world["admin"])).json()["items"][0]
    await client.post(f"/v1/approvals/{ap['id']}/reject", headers=world["admin"], json={"reason": "no"})
    r, _ = await run(ex, world, tool="send_email", args=MAIL, action_id="act_rej")
    assert r.status_code == 403 and r.json()["error"]["code"] == "APPROVAL_REJECTED"


async def test_same_action_id_runs_only_once(ex, client, world):
    await require_approval(client, world)
    await run(ex, world, tool="send_email", args=MAIL, action_id="act_once")
    ap = (await client.get("/v1/approvals?status=PENDING", headers=world["admin"])).json()["items"][0]
    await client.post(f"/v1/approvals/{ap['id']}/approve", headers=world["admin"], json={})
    first, _ = await run(ex, world, tool="send_email", args=MAIL, action_id="act_once")
    again, _ = await run(ex, world, tool="send_email", args=MAIL, action_id="act_once")
    assert first.json()["executed"] is True and "replayed" not in first.json()
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert again.json()["result"]["message_id"] == first.json()["result"]["message_id"]  # not run a second time


async def test_token_cannot_be_reused(client, world):
    """The one-time token GuardRail issues is consumed by the first redemption."""
    await require_approval(client, world)
    r = await client.post("/v1/actions/evaluate", headers={"X-API-Key": world["key"]}, json={
        "agent_id": "support-agent-01", "action_id": "act_tok", "tool": "send_email", "environment": "staging",
        "arguments": MAIL})
    ap_id = r.json()["approval_id"]
    await client.post(f"/v1/approvals/{ap_id}/approve", headers=world["admin"], json={})
    token = (await client.get("/v1/actions/act_tok/status", headers={"X-API-Key": world["key"]})).json()["approval_token"]
    bind = {"token": token, "action_id": "act_tok", "tool": "send_email", "environment": "staging", "arguments": MAIL}
    first = (await client.post("/v1/approvals/verify-token", headers={"X-API-Key": world["key"]}, json=bind)).json()
    second = (await client.post("/v1/approvals/verify-token", headers={"X-API-Key": world["key"]}, json=bind)).json()
    assert first["valid"] is True
    assert second["valid"] is False and second["reason"] == "UNKNOWN_OR_EXPIRED"


async def _approved_token(client, world, action_id, args=MAIL):
    await require_approval(client, world)
    r = await client.post("/v1/actions/evaluate", headers={"X-API-Key": world["key"]}, json={
        "agent_id": "support-agent-01", "action_id": action_id, "tool": "send_email", "environment": "staging",
        "arguments": args})
    await client.post(f"/v1/approvals/{r.json()['approval_id']}/approve", headers=world["admin"], json={})
    st = (await client.get(f"/v1/actions/{action_id}/status", headers={"X-API-Key": world["key"]})).json()
    return st["approval_token"]


async def test_token_is_bound_to_tool_arguments_and_action(client, world):
    verify = lambda body: client.post("/v1/approvals/verify-token", headers={"X-API-Key": world["key"]}, json=body)  # noqa: E731
    base = {"environment": "staging", "tool": "send_email", "arguments": MAIL}
    for label, change in (
        ("different arguments", {"arguments": {**MAIL, "to": "attacker@example.com"}}),
        ("different tool", {"tool": "delete_database_records", "arguments": {"table": "t", "limit": 1}}),
        ("different environment", {"environment": "production"}),
        ("different action", {"action_id": "act_other"}),
    ):
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        token = await _approved_token(client, world, action_id)
        r = (await verify({"token": token, "action_id": action_id, **base, **change})).json()
        assert r["valid"] is False, label
        # a refused presentation burns the token: it cannot be retried with the right arguments
        r2 = (await verify({"token": token, "action_id": action_id, **base})).json()
        assert r2["valid"] is False, label


async def test_token_for_other_agent_is_refused(client, world):
    token = await _approved_token(client, world, "act_agent")
    other = (await client.post("/v1/agents", headers=world["admin"], json={"slug": "other-agent", "name": "O"})).json()
    key = (await client.post(f"/v1/agents/{other['id']}/api-keys", headers=world["admin"], json={"name": "k"})).json()["key"]
    r = (await client.post("/v1/approvals/verify-token", headers={"X-API-Key": key}, json={"token": token})).json()
    assert r["valid"] is False and r["reason"] == "AGENT_MISMATCH"


async def test_expired_token_is_refused_and_nothing_runs(ex, client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "approval_token_ttl_seconds", 1)
    await require_approval(client, world)
    await run(ex, world, tool="send_email", args=MAIL, action_id="act_exp")
    ap = (await client.get("/v1/approvals?status=PENDING", headers=world["admin"])).json()["items"][0]
    await client.post(f"/v1/approvals/{ap['id']}/approve", headers=world["admin"], json={})
    await asyncio.sleep(1.3)  # the token's lifetime ends before the executor redeems it
    r, _ = await run(ex, world, tool="send_email", args=MAIL, action_id="act_exp")
    assert r.status_code == 403 and r.json()["executed"] is False
    assert r.json()["error"]["code"] in ("APPROVAL_TOKEN_INVALID", "APPROVAL_TOKEN_UNAVAILABLE")


async def test_guardrail_down_blocks_the_action(redis, world):
    class Down(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    async with httpx.AsyncClient(transport=Down(), base_url="http://guardrail") as dead:
        app = create_executor_app(guardrail_http=dead, redis=redis)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://executor") as c:
            r = await c.post("/v1/execute", headers={"X-API-Key": world["key"]}, json={
                "agent_id": "support-agent-01", "action_id": "act_down", "tool": "read_logs",
                "environment": "staging", "arguments": {}})
    assert r.status_code == 503
    assert r.json()["executed"] is False and r.json()["error"]["code"] == "GUARDRAIL_UNAVAILABLE"


async def test_guardrail_500_also_blocks(redis, world):
    def boom(request):
        return httpx.Response(500, json={"detail": "oops"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="http://guardrail") as bad:
        app = create_executor_app(guardrail_http=bad, redis=redis)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://executor") as c:
            r = await c.post("/v1/execute", headers={"X-API-Key": world["key"]}, json={
                "agent_id": "support-agent-01", "action_id": "act_500", "tool": "read_logs",
                "environment": "staging", "arguments": {}})
    assert r.status_code == 503 and r.json()["executed"] is False
