import uuid

from sqlalchemy import select

from app.models import ApiKey
from tests.conftest import add_member, auth, evaluate, register


async def test_api_key_is_shown_once_and_stored_hashed(client, world, sessionmaker):
    assert world["key"].startswith("grk_")
    async with sessionmaker() as s:
        keys = (await s.execute(select(ApiKey))).scalars().all()
    assert len(keys) == 1
    assert world["key"] not in keys[0].key_hash and len(keys[0].key_hash) == 64
    listing = await client.get("/v1/api-keys", headers=world["admin"])
    text = listing.text
    assert world["key"] not in text and "key_hash" not in text
    assert listing.json()["items"][0]["prefix"] == world["key"][:12]


async def test_missing_and_invalid_api_key_rejected(client, world):
    body = {"agent_id": "support-agent-01", "action_id": "a1", "tool": "read_logs", "environment": "dev"}
    r = await client.post("/v1/actions/evaluate", json=body)
    assert r.status_code == 401 and r.json()["error"]["code"] == "MISSING_API_KEY"
    r = await client.post("/v1/actions/evaluate", json=body, headers={"X-API-Key": "grk_not-a-real-key"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_API_KEY"


async def test_revoked_key_rejected(client, world):
    assert (await evaluate(client, world)).status_code == 200
    r = await client.delete(f"/v1/api-keys/{world['key_id']}", headers=world["manager"])
    assert r.status_code == 200 and r.json()["revoked_at"]
    r = await evaluate(client, world)
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_API_KEY"


async def test_expired_key_rejected(client, world, sessionmaker):
    from datetime import timedelta

    from app.models.base import utcnow

    async with sessionmaker() as s:
        key = (await s.execute(select(ApiKey))).scalar_one()
        key.expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    assert (await evaluate(client, world)).status_code == 401


async def test_key_cannot_act_for_another_agent(client, world):
    await client.post("/v1/agents", headers=world["admin"], json={"slug": "other-agent", "name": "Other"})
    r = await evaluate(client, world, agent_id="other-agent")
    assert r.status_code == 403 and r.json()["error"]["code"] == "AGENT_MISMATCH"


async def test_disabled_agent_cannot_evaluate(client, world):
    r = await client.patch(f"/v1/agents/{world['agent']['id']}", headers=world["manager"], json={"status": "DISABLED"})
    assert r.status_code == 200
    r = await evaluate(client, world)
    assert r.status_code == 403 and r.json()["error"]["code"] == "AGENT_DISABLED"


async def test_duplicate_agent_slug_conflicts(client, world):
    r = await client.post("/v1/agents", headers=world["admin"], json={"slug": "support-agent-01", "name": "Dup"})
    assert r.status_code == 409


async def test_invalid_agent_slug_rejected(client, world):
    r = await client.post("/v1/agents", headers=world["admin"], json={"slug": "Bad Slug!", "name": "x"})
    assert r.status_code == 422


async def test_agent_listing_pagination_and_filter(client, world):
    for i in range(5):
        await client.post("/v1/agents", headers=world["admin"], json={"slug": f"extra-agent-{i}", "name": f"Extra {i}"})
    r = await client.get("/v1/agents?page=1&page_size=3", headers=world["viewer"])
    body = r.json()
    assert len(body["items"]) == 3 and body["total"] == 6 and body["pages"] == 2
    r = await client.get("/v1/agents?search=extra-agent-3", headers=world["viewer"])
    assert [a["slug"] for a in r.json()["items"]] == ["extra-agent-3"]


# ------------------------------------------------------------------ IDOR
async def test_idor_other_org_cannot_see_or_modify_agents_tools_keys(client, world):
    other = auth((await register(client, "mallory@evil-corp.com", "Evil Inc"))["tokens"]["access_token"])
    agent_id, key_id, tool_id = world["agent"]["id"], world["key_id"], world["tool_ids"][0]
    assert (await client.get(f"/v1/agents/{agent_id}", headers=other)).status_code == 404
    assert (await client.patch(f"/v1/agents/{agent_id}", headers=other, json={"name": "pwned"})).status_code == 404
    assert (await client.get(f"/v1/agents/{agent_id}/tools", headers=other)).status_code == 404
    assert (await client.post(f"/v1/agents/{agent_id}/api-keys", headers=other, json={"name": "x"})).status_code == 404
    assert (await client.delete(f"/v1/api-keys/{key_id}", headers=other)).status_code == 404
    assert (await client.patch(f"/v1/tools/{tool_id}", headers=other, json={"is_active": False})).status_code == 404
    assert (await client.get("/v1/agents", headers=other)).json()["total"] == 0
    assert (await client.get("/v1/api-keys", headers=other)).json()["total"] == 0
    # the victim's data is untouched
    assert (await client.get(f"/v1/agents/{agent_id}", headers=world["admin"])).json()["name"] == "Support"


async def test_idor_cannot_assign_foreign_tools(client, world):
    other = auth((await register(client, "mallory@evil-corp.com", "Evil Inc"))["tokens"]["access_token"])
    mine = (await client.post("/v1/agents", headers=other, json={"slug": "evil-agent", "name": "Evil"})).json()
    r = await client.put(f"/v1/agents/{mine['id']}/tools", headers=other, json={"tool_ids": world["tool_ids"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_TOOL_IDS"


async def test_idor_random_uuid_is_404_not_500(client, world):
    assert (await client.get(f"/v1/agents/{uuid.uuid4()}", headers=world["admin"])).status_code == 404
    assert (await client.get("/v1/agents/not-a-uuid", headers=world["admin"])).status_code == 422


async def test_idor_action_history_and_approvals_scoped(client, world):
    await make_require_approval_policy(client, world)
    r = await evaluate(client, world, tool="send_email", environment="production")
    assert r.status_code == 202
    approval_id = r.json()["approval_id"]
    other = auth((await register(client, "mallory@evil-corp.com", "Evil Inc"))["tokens"]["access_token"])
    assert (await client.get(f"/v1/approvals/{approval_id}", headers=other)).status_code == 404
    assert (await client.post(f"/v1/approvals/{approval_id}/approve", headers=other, json={})).status_code == 404
    assert (await client.get("/v1/approvals", headers=other)).json()["total"] == 0
    assert (await client.get("/v1/action-history", headers=other)).json()["total"] == 0
    assert (await client.get("/v1/audit-logs", headers=other)).json()["total"] == 1  # only their own org-created entry


async def make_require_approval_policy(client, world):
    from tests.conftest import make_policy

    return await make_policy(client, world["admin"], name="approve-email-prod", effect="REQUIRE_APPROVAL", priority=10,
                             reason_code="PROD_EMAIL_APPROVAL", message="Production email needs approval",
                             rules=[{"field": "tool", "operator": "eq", "value": "send_email"},
                                    {"field": "environment", "operator": "eq", "value": "production"}])
