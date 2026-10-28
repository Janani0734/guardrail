import jwt
import pytest

from app.core.config import get_settings
from tests.conftest import auth, register


async def test_register_and_login(client):
    reg = await register(client)
    assert reg["role"] == "ADMIN"
    assert "password" not in str(reg).lower().replace("password_hash", "")
    r = await client.post("/v1/auth/login", json={"email": "admin@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200
    body = r.json()
    assert body["tokens"]["token_type"] == "bearer" and body["organization"]["name"] == "Acme Corp"
    assert "password_hash" not in r.text


async def test_duplicate_email_conflicts(client):
    await register(client)
    r = await client.post("/v1/auth/register", json={
        "email": "ADMIN@example.com", "password": "another-long-password", "full_name": "X", "organization_name": "Other"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_weak_password_rejected(client):
    r = await client.post("/v1/auth/register", json={
        "email": "a@b.co", "password": "short", "full_name": "X", "organization_name": "Org"})
    assert r.status_code == 422


async def test_wrong_password_and_unknown_user_look_identical(client):
    await register(client)
    bad = await client.post("/v1/auth/login", json={"email": "admin@example.com", "password": "nope-nope-nope"})
    unknown = await client.post("/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_throttle(client):
    await register(client)
    codes = []
    for _ in range(get_settings().login_max_attempts + 2):
        r = await client.post("/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-wrong-wrong"})
        codes.append(r.status_code)
    assert codes[-1] == 429 and "retry-after" in r.headers


async def test_jwt_protects_routes(client):
    assert (await client.get("/v1/agents")).status_code == 401
    assert (await client.get("/v1/agents", headers=auth("garbage"))).status_code == 401


async def test_refresh_token_cannot_be_used_as_access_token(client):
    reg = await register(client)
    r = await client.get("/v1/agents", headers=auth(reg["tokens"]["refresh_token"]))
    assert r.status_code == 401


async def test_expired_access_token_rejected(client):
    reg = await register(client)
    s = get_settings()
    payload = jwt.decode(reg["tokens"]["access_token"], s.jwt_secret, algorithms=[s.jwt_algorithm])
    payload["exp"] = payload["iat"] - 10
    expired = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
    r = await client.get("/v1/agents", headers=auth(expired))
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_token_signed_with_other_secret_rejected(client):
    reg = await register(client)
    payload = jwt.decode(reg["tokens"]["access_token"], options={"verify_signature": False})
    forged = jwt.encode(payload, "attacker-secret-attacker-secret-1234", algorithm="HS256")
    assert (await client.get("/v1/agents", headers=auth(forged))).status_code == 401


async def test_refresh_rotates_and_old_token_is_revoked(client):
    reg = await register(client)
    old = reg["tokens"]["refresh_token"]
    r1 = await client.post("/v1/auth/refresh", json={"refresh_token": old})
    assert r1.status_code == 200
    r2 = await client.post("/v1/auth/refresh", json={"refresh_token": old})
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "TOKEN_REVOKED"
    new = r1.json()["tokens"]["refresh_token"]
    assert (await client.post("/v1/auth/refresh", json={"refresh_token": new})).status_code == 200


async def test_logout_revokes_refresh_token(client):
    reg = await register(client)
    rt = reg["tokens"]["refresh_token"]
    assert (await client.post("/v1/auth/logout", json={"refresh_token": rt})).status_code == 200
    assert (await client.post("/v1/auth/refresh", json={"refresh_token": rt})).status_code == 401


async def test_me(client):
    reg = await register(client)
    r = await client.get("/v1/auth/me", headers=auth(reg["tokens"]["access_token"]))
    assert r.status_code == 200 and r.json()["user"]["email"] == "admin@example.com"


async def test_passwords_are_hashed_with_bcrypt(client, sessionmaker):
    from sqlalchemy import select

    from app.models import User

    await register(client)
    async with sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
    assert user.password_hash.startswith("$2") and "correct-horse" not in user.password_hash
