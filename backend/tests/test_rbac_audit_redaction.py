from sqlalchemy import select, text, update

from app.models import AuditLog
from app.models.actions import ImmutableAuditError
from app.services.audit_service import AuditService
from app.utils.redaction import REDACTED, redact_text, redact_value
from tests.conftest import add_member, auth, evaluate, make_policy, register

import pytest


# ------------------------------------------------------------------ RBAC
async def test_role_matrix(client, world):
    agent = {"slug": "rbac-agent", "name": "RBAC"}
    policy = {"name": "rbac-policy", "effect": "BLOCK", "rules": [{"field": "tool", "operator": "eq", "value": "x"}]}
    # VIEWER: read only
    assert (await client.get("/v1/agents", headers=world["viewer"])).status_code == 200
    assert (await client.get("/v1/policies", headers=world["viewer"])).status_code == 200
    assert (await client.get("/v1/audit-logs", headers=world["viewer"])).status_code == 200
    assert (await client.post("/v1/agents", headers=world["viewer"], json=agent)).status_code == 403
    assert (await client.post("/v1/tools", headers=world["viewer"], json={"name": "t1"})).status_code == 403
    assert (await client.post("/v1/policies", headers=world["viewer"], json=policy)).status_code == 403
    assert (await client.delete(f"/v1/api-keys/{world['key_id']}", headers=world["viewer"])).status_code == 403
    # MANAGER: manage agents/tools/keys/approvals, but not policies or members
    assert (await client.post("/v1/agents", headers=world["manager"], json=agent)).status_code == 201
    assert (await client.post("/v1/tools", headers=world["manager"], json={"name": "t2"})).status_code == 201
    assert (await client.post("/v1/policies", headers=world["manager"], json=policy)).status_code == 403
    assert (await client.get("/v1/members", headers=world["manager"])).status_code == 200
    assert (await client.post("/v1/members", headers=world["manager"], json={
        "email": "x@y.co", "full_name": "X", "password": "long-enough-pass", "role": "VIEWER"})).status_code == 403
    assert (await client.get("/v1/audit-logs/verify", headers=world["manager"])).status_code == 403
    # ADMIN: everything
    assert (await client.post("/v1/policies", headers=world["admin"], json=policy)).status_code == 201
    assert (await client.get("/v1/audit-logs/verify", headers=world["admin"])).status_code == 200


async def test_demotion_takes_effect_immediately(client, world):
    assert (await client.post("/v1/tools", headers=world["manager"], json={"name": "before"})).status_code == 201
    r = await client.patch(f"/v1/members/{(await client.get('/v1/members', headers=world['admin'])).json()[1]['user_id']}",
                           headers=world["admin"], json={"role": "VIEWER"})
    assert r.status_code == 200
    assert (await client.post("/v1/tools", headers=world["manager"], json={"name": "after"})).status_code == 403


async def test_removed_member_loses_access_with_valid_token(client, world):
    members = (await client.get("/v1/members", headers=world["admin"])).json()
    viewer_id = next(m["user_id"] for m in members if m["email"] == "viewer@example.com")
    assert (await client.delete(f"/v1/members/{viewer_id}", headers=world["admin"])).status_code == 204
    assert (await client.get("/v1/agents", headers=world["viewer"])).status_code == 401


async def test_cannot_demote_or_remove_last_admin(client, world):
    r = await client.patch(f"/v1/members/{world['user_id']}", headers=world["admin"], json={"role": "VIEWER"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "LAST_ADMIN"
    assert (await client.delete(f"/v1/members/{world['user_id']}", headers=world["admin"])).status_code == 403


async def test_member_of_two_orgs_gets_org_scoped_tokens(client, world):
    other = await register(client, "boss@other-corp.com", "Other Org")
    await client.post("/v1/members", headers=auth(other["tokens"]["access_token"]), json={
        "email": "admin@example.com", "full_name": "Test", "password": "unused-password-1", "role": "VIEWER"})
    login = await client.post("/v1/auth/login", json={
        "email": "admin@example.com", "password": "correct-horse-battery", "organization_id": other["organization"]["id"]})
    assert login.json()["role"] == "VIEWER" and login.json()["organization"]["name"] == "Other Org"
    headers = auth(login.json()["tokens"]["access_token"])
    assert (await client.get("/v1/agents", headers=headers)).json()["total"] == 0  # not the first org's agents


# ------------------------------------------------------------------ audit log
async def test_audit_chain_verifies_and_detects_tampering(client, world, sessionmaker):
    await make_policy(client, world["admin"], rules=[{"field": "tool", "operator": "eq", "value": "send_email"}])
    for i in range(3):
        await evaluate(client, world, action_id=f"a{i}", tool="send_email")
    ok = (await client.get("/v1/audit-logs/verify", headers=world["admin"])).json()
    assert ok["valid"] is True and ok["checked"] >= 8

    # simulate an attacker with raw SQL access who bypasses the ORM guard
    async with sessionmaker() as s:
        await s.execute(text("UPDATE audit_logs SET details = '{\"tampered\": true}' WHERE seq = 5"))
        await s.commit()
    bad = (await client.get("/v1/audit-logs/verify", headers=world["admin"])).json()
    assert bad["valid"] is False and bad["first_invalid_seq"] == 5


async def test_audit_chain_detects_deleted_rows(client, world, sessionmaker):
    await evaluate(client, world)
    await evaluate(client, world)
    async with sessionmaker() as s:
        await s.execute(text("DELETE FROM audit_logs WHERE seq = 4"))
        await s.commit()
    assert (await client.get("/v1/audit-logs/verify", headers=world["admin"])).json()["valid"] is False


async def test_audit_rows_are_immutable_through_the_orm(sessionmaker, client, world):
    async with sessionmaker() as s:
        entry = (await s.execute(select(AuditLog).limit(1))).scalar_one()
        entry.event_type = "FORGED"
        with pytest.raises(ImmutableAuditError):
            await s.flush()
    async with sessionmaker() as s:
        entry = (await s.execute(select(AuditLog).limit(1))).scalar_one()
        await s.delete(entry)
        with pytest.raises(ImmutableAuditError):
            await s.flush()


async def test_audit_entries_are_sequential_per_org_and_filterable(client, world):
    await evaluate(client, world)
    logs = (await client.get("/v1/audit-logs?order=asc&page_size=100", headers=world["viewer"])).json()
    seqs = [e["seq"] for e in logs["items"]]
    assert seqs == list(range(1, len(seqs) + 1))
    assert logs["items"][0]["prev_hash"] == "0" * 64
    for prev, cur in zip(logs["items"], logs["items"][1:]):
        assert cur["prev_hash"] == prev["entry_hash"]
    only = (await client.get("/v1/audit-logs?event_type=API_KEY_CREATED", headers=world["viewer"])).json()
    assert only["total"] == 1 and "key_hash" not in only["items"][0]["details"]


async def test_audit_logs_record_config_changes(client, world):
    types = {e["event_type"] for e in (await client.get("/v1/audit-logs?page_size=100", headers=world["admin"])).json()["items"]}
    assert {"ORGANIZATION_CREATED", "AGENT_CREATED", "TOOL_CREATED", "AGENT_TOOLS_UPDATED", "API_KEY_CREATED",
            "MEMBER_ADDED", "USER_LOGIN"} <= types


# ------------------------------------------------------------------ redaction unit tests
def test_redact_by_key_name_and_pattern():
    data = {"user": "bob", "password": "p@ss", "api_key": "abc", "config": {"client_secret": "zzz", "retries": 3},
            "items": [{"token": "t"}, "plain"], "max_tokens": 100, "empty_password": ""}
    out, n = redact_value(data)
    assert out["password"] == out["api_key"] == REDACTED
    assert out["config"] == {"client_secret": REDACTED, "retries": 3}
    assert out["items"][0]["token"] == REDACTED and out["items"][1] == "plain"
    assert out["max_tokens"] == 100 and out["user"] == "bob"  # "max_tokens" is not a secret
    assert n == 4 and data["password"] == "p@ss"  # input untouched


@pytest.mark.parametrize("secret", [
    "AKIAIOSFODNN7EXAMPLE", "ghp_" + "a" * 36, "sk_live_" + "b" * 24, "xoxb-1234567890-abcdefghij",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop", "grk_" + "c" * 30,
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
])
def test_redact_known_token_formats(secret):
    text_, n = redact_text(f"value is {secret} ok")
    assert secret not in text_ and n >= 1 and "[REDACTED]" in text_


def test_redact_connection_string_and_kv():
    t, n = redact_text("postgres://admin:s3cr3tpw@db:5432/x and password=hunter22")
    assert "s3cr3tpw" not in t and "hunter22" not in t and "admin" in t and n == 2


def test_redact_leaves_benign_text_alone():
    s = "Delete 1000 expired rows from old_logs table"
    assert redact_text(s) == (s, 0)
