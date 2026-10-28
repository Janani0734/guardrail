import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import Forbidden, Unauthorized
from app.core.redis import get_redis
from app.core.security import decode_token, hash_api_key
from app.models import Agent, ApiKey
from app.models.base import utcnow
from app.models.enums import AgentStatus, Role
from app.repositories.agents import ApiKeyRepository
from app.repositories.identity import MembershipRepository
from app.services.principal import Principal

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token from /v1/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


async def get_principal(
    session: SessionDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> Principal:
    if creds is None:
        raise Unauthorized("Missing bearer token", code="MISSING_TOKEN", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_token(creds.credentials, "access")
    try:
        user_id, org_id = uuid.UUID(payload["sub"]), uuid.UUID(payload["org"])
    except (KeyError, ValueError) as exc:
        raise Unauthorized("Invalid token", code="INVALID_TOKEN") from exc
    # Role is re-read from the database on every request, so demotions/removals take effect immediately
    # instead of waiting for the access token to expire.
    membership = await MembershipRepository(session).get(org_id, user_id)
    if not membership or not membership.user.is_active:
        raise Unauthorized("Account is no longer valid for this organization", code="INVALID_TOKEN")
    u = membership.user
    return Principal(user_id=u.id, email=u.email, full_name=u.full_name, org_id=org_id, role=membership.role)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(minimum: Role) -> Callable[..., Principal]:
    async def checker(principal: PrincipalDep) -> Principal:
        if not principal.at_least(minimum):
            raise Forbidden(f"Requires role {minimum.value} or higher", code="INSUFFICIENT_ROLE")
        return principal

    return checker


Viewer = Annotated[Principal, Depends(require_role(Role.VIEWER))]
Manager = Annotated[Principal, Depends(require_role(Role.MANAGER))]
Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]


async def get_agent_auth(
    session: SessionDep, x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> tuple[ApiKey, Agent]:
    if not x_api_key:
        raise Unauthorized("Missing X-API-Key header", code="MISSING_API_KEY")
    found = await ApiKeyRepository(session).get_by_hash(hash_api_key(x_api_key))
    # One generic error for unknown / revoked / expired keys so the endpoint can't be used to probe key state.
    if not found:
        raise Unauthorized("Invalid API key", code="INVALID_API_KEY")
    key, agent = found
    now = utcnow()
    if key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= now):
        raise Unauthorized("Invalid API key", code="INVALID_API_KEY")
    if agent.status != AgentStatus.ACTIVE:
        raise Forbidden("Agent is disabled", code="AGENT_DISABLED")
    return key, agent


AgentAuth = Annotated[tuple[ApiKey, Agent], Depends(get_agent_auth)]
