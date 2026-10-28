from datetime import timedelta

from sqlalchemy import select

from app.models import Approval
from app.models.base import utcnow
from app.workers.expiry import run_once
from tests.conftest import evaluate, make_policy

KEY = lambda w: {"X-API-Key": w["key"]}  # noqa: E731


async def pending(client, world, **kw):
    await make_policy(client, world["admin"], name=f"needs-approval-{kw.get('tag', 0)}", effect="REQUIRE_APPROVAL",
                      rules=[{"field": "estimated_cost", "operator": "gt", "value": 10}], reason_code="HIGH_COST",
                      config=kw.get("config", {}))
    r = await evaluate(client, world, action_id=kw.get("action_id", "act_big"), estimated_cost=50)
    assert r.status_code == 202, r.text
    return r.json()


async def test_approve_flow_end_to_end(client, world):
    body = await pending(client, world)
    listing = (await client.get("/v1/approvals?status=PENDING", headers=world["viewer"])).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == body["approval_id"]
    assert listing["items"][0]["tool"] == "read_logs"

    # agent polls: still pending, no token yet
    st = (await client.get("/v1/actions/act_big/status", headers=KEY(world))).json()
    assert st["status"] == "PENDING_APPROVAL" and st["approval_status"] == "PENDING" and st["approval_token"] is None

    r = await client.post(f"/v1/approvals/{body['approval_id']}/approve", headers=world["manager"],
                          json={"reason": "Looks fine"})
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "APPROVED" and done["decided_by_email"] == "manager@example.com"
    assert done["decision_reason"] == "Looks fine" and done["decided_at"]

    st = (await client.get("/v1/actions/act_big/status", headers=KEY(world))).json()
    assert st["status"] == "APPROVED" and st["approval_token"].startswith("apt_")
    token = st["approval_token"]
    # token is handed out once
    assert (await client.get("/v1/actions/act_big/status", headers=KEY(world))).json()["approval_token"] is None
    # and can be redeemed exactly once, only by the owning agent
    v1 = (await client.post("/v1/approvals/verify-token", headers=KEY(world), json={"token": token})).json()
    assert v1 == {"valid": True, "action_id": "act_big", "approval_id": body["approval_id"]}
    v2 = (await client.post("/v1/approvals/verify-token", headers=KEY(world), json={"token": token})).json()
    assert v2["valid"] is False
    # the action now shows APPROVED in history
    hist = (await client.get("/v1/action-history?status=APPROVED", headers=world["viewer"])).json()
    assert hist["total"] == 1


async def test_token_is_bound_to_the_issuing_agent(client, world):
    body = await pending(client, world)
    await client.post(f"/v1/approvals/{body['approval_id']}/approve", headers=world["admin"], json={})
    token = (await client.get("/v1/actions/act_big/status", headers=KEY(world))).json()["approval_token"]
    other_agent = (await client.post("/v1/agents", headers=world["admin"], json={"slug": "other", "name": "Other"})).json()
    other_key = (await client.post(f"/v1/agents/{other_agent['id']}/api-keys", headers=world["admin"], json={"name": "k"})).json()["key"]
    r = await client.post("/v1/approvals/verify-token", headers={"X-API-Key": other_key}, json={"token": token})
    assert r.json()["valid"] is False


async def test_reject_flow(client, world):
    body = await pending(client, world)
    r = await client.post(f"/v1/approvals/{body['approval_id']}/reject", headers=world["admin"], json={"reason": "Too risky"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    st = (await client.get("/v1/actions/act_big/status", headers=KEY(world))).json()
    assert st["status"] == "REJECTED" and st["approval_token"] is None and st["decision_reason"] == "Too risky"


async def test_cannot_decide_twice(client, world):
    body = await pending(client, world)
    url = f"/v1/approvals/{body['approval_id']}"
    assert (await client.post(f"{url}/approve", headers=world["admin"], json={})).status_code == 200
    r = await client.post(f"{url}/reject", headers=world["admin"], json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPROVAL_NOT_PENDING"


async def test_viewer_cannot_decide(client, world):
    body = await pending(client, world)
    r = await client.post(f"/v1/approvals/{body['approval_id']}/approve", headers=world["viewer"], json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "INSUFFICIENT_ROLE"


async def test_custom_ttl_from_policy(client, world, sessionmaker):
    body = await pending(client, world, config={"ttl_minutes": 2})
    async with sessionmaker() as s:
        ap = (await s.execute(select(Approval))).scalar_one()
    delta = ap.expires_at - utcnow()
    assert timedelta(seconds=60) < delta <= timedelta(minutes=2)
    assert body["expires_at"].endswith("Z")


async def _age_approval(sessionmaker, minutes=1):
    async with sessionmaker() as s:
        ap = (await s.execute(select(Approval))).scalar_one()
        ap.expires_at = utcnow() - timedelta(minutes=minutes)
        await s.commit()


async def test_worker_expires_overdue_approvals(client, world, sessionmaker, redis):
    body = await pending(client, world)
    assert await run_once(redis) == 0  # nothing overdue yet
    await _age_approval(sessionmaker)
    assert await run_once(redis) == 1
    async with sessionmaker() as s:
        ap = (await s.execute(select(Approval))).scalar_one()
    assert ap.status.value == "EXPIRED"
    hist = (await client.get("/v1/action-history?status=EXPIRED", headers=world["viewer"])).json()
    assert hist["total"] == 1 and hist["items"][0]["status"] == "EXPIRED"
    r = await client.post(f"/v1/approvals/{body['approval_id']}/approve", headers=world["admin"], json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPROVAL_NOT_PENDING"
    audit = (await client.get("/v1/audit-logs?event_type=APPROVAL_EXPIRED", headers=world["admin"])).json()
    assert audit["total"] == 1 and audit["items"][0]["actor_type"] == "SYSTEM"
    assert await run_once(redis) == 0  # idempotent


async def test_worker_lock_prevents_concurrent_sweeps(client, world, sessionmaker, redis):
    await pending(client, world)
    await _age_approval(sessionmaker)
    await redis.set("lock:approval-expiry", "another-worker", ex=30)
    assert await run_once(redis) == 0
    await redis.delete("lock:approval-expiry")
    assert await run_once(redis) == 1


async def test_deciding_an_overdue_approval_expires_it_lazily(client, world, sessionmaker):
    body = await pending(client, world)
    await _age_approval(sessionmaker)
    r = await client.post(f"/v1/approvals/{body['approval_id']}/approve", headers=world["admin"], json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPROVAL_EXPIRED"
    async with sessionmaker() as s:
        assert (await s.execute(select(Approval))).scalar_one().status.value == "EXPIRED"


async def test_pending_list_hides_overdue_and_status_poll_expires_lazily(client, world, sessionmaker):
    await pending(client, world)
    await _age_approval(sessionmaker)
    assert (await client.get("/v1/approvals?status=PENDING", headers=world["viewer"])).json()["total"] == 0
    st = (await client.get("/v1/actions/act_big/status", headers=KEY(world))).json()
    assert st["status"] == "EXPIRED" and st["approval_status"] == "EXPIRED"


async def test_rejection_counts_toward_repeat_block(client, world):
    await make_policy(client, world["admin"], policy_type="REPEATED_ACTION", config={"threshold": 2})
    await make_policy(client, world["admin"], name="appr", effect="REQUIRE_APPROVAL",
                      rules=[{"field": "tool", "operator": "eq", "value": "send_email"}])
    for i in range(2):
        r = await evaluate(client, world, action_id=f"rej-{i}", tool="send_email", arguments={"to": "x@y.z"})
        await client.post(f"/v1/approvals/{r.json()['approval_id']}/reject", headers=world["admin"], json={})
    r = await evaluate(client, world, action_id="rej-2", tool="send_email", arguments={"to": "x@y.z"})
    assert r.json()["reason_code"] == "REPEATED_ACTION_BLOCKED"


async def test_decisions_are_audited(client, world):
    body = await pending(client, world)
    await client.post(f"/v1/approvals/{body['approval_id']}/approve", headers=world["manager"], json={"reason": "ok"})
    logs = (await client.get("/v1/audit-logs?event_type=APPROVAL_APPROVED", headers=world["viewer"])).json()
    assert logs["total"] == 1
    entry = logs["items"][0]
    assert entry["actor_label"] == "manager@example.com" and entry["details"]["reason"] == "ok"


async def test_analytics_reflect_activity_and_cache_invalidates(client, world):
    await pending(client, world)
    a = (await client.get("/v1/analytics?days=7", headers=world["viewer"])).json()
    assert a["totals"]["total"] == 1 and a["totals"]["approvals_required"] == 1 and a["totals"]["pending_approvals"] == 1
    assert a["cached"] is False
    assert (await client.get("/v1/analytics?days=7", headers=world["viewer"])).json()["cached"] is True
    await evaluate(client, world)  # new action bumps the cache version
    b = (await client.get("/v1/analytics?days=7", headers=world["viewer"])).json()
    assert b["cached"] is False and b["totals"]["total"] == 2
    assert b["agent_activity"][0]["agent"] == "support-agent-01" and b["timeseries"]
