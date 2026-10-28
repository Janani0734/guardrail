import os
import uuid
from pathlib import Path

# Must be set before app modules import settings. Tests use SQLite (aiosqlite) + fakeredis so they are hermetic.
os.environ.setdefault("BCRYPT_ROUNDS", "4")
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-0123456789abcdef0123456789")
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-0123456789abcdef0123456789")

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.database import Base, set_sessionmaker  # noqa: E402
from app.core.redis import set_redis_client  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest_asyncio.fixture
async def engine(tmp_path: Path):
    """SQLite by default. Set TEST_DATABASE_URL=postgresql+asyncpg://... to run the same suite on PostgreSQL
    (the target database is dropped and recreated per test - point it at a throwaway database!)."""
    pg_url = os.environ.get("TEST_DATABASE_URL")
    if pg_url:
        eng = create_async_engine(pg_url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    else:
        eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", connect_args={"timeout": 30})

        @event.listens_for(eng.sync_engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    set_sessionmaker(maker)
    return maker


@pytest_asyncio.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis_client(client)
    yield client
    await client.flushall()
    await client.aclose()
    set_redis_client(None)


@pytest_asyncio.fixture
async def client(sessionmaker, redis):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def register(client: AsyncClient, email: str = "admin@example.com", org: str = "Acme Corp",
                   password: str = "correct-horse-battery") -> dict:
    r = await client.post("/v1/auth/register", json={
        "email": email, "password": password, "full_name": "Test User", "organization_name": org})
    assert r.status_code == 201, r.text
    return r.json()


async def add_member(client: AsyncClient, admin_headers: dict, email: str, role: str) -> dict:
    password = "member-password-123"
    r = await client.post("/v1/members", headers=admin_headers, json={
        "email": email, "full_name": role.title(), "password": password, "role": role})
    assert r.status_code == 201, r.text
    login = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return auth(login.json()["tokens"]["access_token"])


async def make_policy(client: AsyncClient, headers: dict, **overrides) -> dict:
    body = {"name": f"policy-{uuid.uuid4().hex[:6]}", "policy_type": "RULE", "effect": "BLOCK", "priority": 100,
            "reason_code": "TEST_POLICY", "rules": []}
    body.update(overrides)
    r = await client.post("/v1/policies", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def world(client):
    """An organisation with admin/manager/viewer users, one agent, three tools and one API key."""
    reg = await register(client)
    admin = auth(reg["tokens"]["access_token"])
    manager = await add_member(client, admin, "manager@example.com", "MANAGER")
    viewer = await add_member(client, admin, "viewer@example.com", "VIEWER")

    agent = (await client.post("/v1/agents", headers=admin, json={"slug": "support-agent-01", "name": "Support"})).json()
    tool_ids = []
    for name, risk in (("read_logs", "LOW"), ("delete_database_records", "HIGH"), ("send_email", "MEDIUM")):
        t = await client.post("/v1/tools", headers=admin, json={"name": name, "risk_level": risk})
        assert t.status_code == 201, t.text
        tool_ids.append(t.json()["id"])
    r = await client.put(f"/v1/agents/{agent['id']}/tools", headers=admin, json={"tool_ids": tool_ids})
    assert r.status_code == 200, r.text
    key = (await client.post(f"/v1/agents/{agent['id']}/api-keys", headers=admin, json={"name": "primary"})).json()
    return {"admin": admin, "manager": manager, "viewer": viewer, "agent": agent, "tool_ids": tool_ids,
            "key": key["key"], "key_id": key["id"], "org_id": reg["organization"]["id"],
            "user_id": reg["user"]["id"], "reg": reg}


async def evaluate(client: AsyncClient, world: dict, **overrides):
    body = {"agent_id": world["agent"]["slug"], "action_id": f"act_{uuid.uuid4().hex[:10]}", "tool": "read_logs",
            "environment": "staging", "arguments": {}, "estimated_cost": 1}
    body.update(overrides)
    return await client.post("/v1/actions/evaluate", headers={"X-API-Key": world["key"]}, json=body)
