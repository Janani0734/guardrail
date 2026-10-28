import re
import secrets
from functools import lru_cache
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import Conflict, Forbidden, RateLimited, Unauthorized
from app.core.security import (
    create_access_token, create_refresh_token, decode_token, hash_password, verify_password,
)
from app.models import Membership, Organization, User
from app.models.enums import ActorType, Role
from app.repositories.identity import MembershipRepository, OrganizationRepository, UserRepository
from app.schemas.auth import AuthResponse, LoginRequest, OrganizationOut, RegisterRequest, TokenPair, UserOut
from app.services.audit_service import AuditService
from app.utils import redis_keys



@lru_cache
def _dummy_hash() -> str:
    return hash_password("timing-equalizer-password")


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{secrets.token_hex(3)}"


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis):
        self.session = session
        self.redis = redis
        self.users = UserRepository(session)
        self.orgs = OrganizationRepository(session)
        self.memberships = MembershipRepository(session)
        self.audit = AuditService(session)
        self.settings = get_settings()

    async def _issue(self, user: User, org: Organization, role: Role) -> AuthResponse:
        access, expires_in = create_access_token(user.id, org.id)
        refresh, _, _ = create_refresh_token(user.id, org.id)
        return AuthResponse(
            tokens=TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in),
            user=UserOut.model_validate(user), organization=OrganizationOut.model_validate(org), role=role,
        )

    async def register(self, data: RegisterRequest) -> AuthResponse:
        if await self.users.get_by_email(data.email):
            raise Conflict("An account with this email already exists", code="EMAIL_TAKEN")
        user = self.users.add(User(email=data.email, password_hash=hash_password(data.password), full_name=data.full_name))
        org = self.orgs.add(Organization(name=data.organization_name, slug=slugify(data.organization_name)))
        await self.session.flush()
        self.memberships.add(Membership(organization_id=org.id, user_id=user.id, role=Role.ADMIN))
        await self.audit.log(
            org_id=org.id, actor_type=ActorType.USER, actor_id=user.id, actor_label=user.email,
            event_type="ORGANIZATION_CREATED", entity_type="organization", entity_id=org.id,
            details={"name": org.name},
        )
        await self.session.commit()
        return await self._issue(user, org, Role.ADMIN)

    async def _check_login_throttle(self, email: str) -> None:
        key = redis_keys.login_attempts(email)
        attempts = await self.redis.incr(key)
        if attempts == 1:
            await self.redis.expire(key, self.settings.login_window_seconds)
        if attempts > self.settings.login_max_attempts:
            ttl = await self.redis.ttl(key)
            raise RateLimited(
                "Too many login attempts. Try again later.", code="LOGIN_THROTTLED",
                headers={"Retry-After": str(max(ttl, 1))},
            )

    async def login(self, data: LoginRequest) -> AuthResponse:
        await self._check_login_throttle(data.email)
        user = await self.users.get_by_email(data.email)
        if user:
            password_ok = verify_password(data.password, user.password_hash)
        else:
            verify_password(data.password, _dummy_hash())  # equalise timing so unknown emails aren't distinguishable
            password_ok = False
        if not user or not password_ok or not user.is_active:
            raise Unauthorized("Invalid email or password", code="INVALID_CREDENTIALS")
        if data.organization_id:
            membership = await self.memberships.get(data.organization_id, user.id)
            if not membership:
                raise Forbidden("You are not a member of that organization", code="NOT_A_MEMBER")
        else:
            membership = await self.memberships.first_for_user(user.id)
            if not membership:
                raise Forbidden("Account has no organization membership", code="NO_MEMBERSHIP")
        user.last_login_at = datetime.now(UTC)
        await self.audit.log(
            org_id=membership.organization_id, actor_type=ActorType.USER, actor_id=user.id, actor_label=user.email,
            event_type="USER_LOGIN", entity_type="user", entity_id=user.id,
        )
        await self.session.commit()
        await self.redis.delete(redis_keys.login_attempts(data.email))
        return await self._issue(user, membership.organization, membership.role)

    async def refresh(self, refresh_token: str) -> AuthResponse:
        payload = decode_token(refresh_token, "refresh")
        jti = payload["jti"]
        if await self.redis.exists(redis_keys.revoked_jti(jti)):
            raise Unauthorized("Refresh token has been revoked", code="TOKEN_REVOKED")
        user = await self.users.get(uuid.UUID(payload["sub"]))
        membership = await self.memberships.get(uuid.UUID(payload["org"]), uuid.UUID(payload["sub"]))
        if not user or not user.is_active or not membership:
            raise Unauthorized("Account is no longer valid", code="INVALID_TOKEN")
        await self._revoke(jti, payload["exp"])  # rotation: each refresh token works once
        return await self._issue(user, membership.organization, membership.role)

    async def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            payload = decode_token(refresh_token, "refresh")
        except Unauthorized:
            return
        await self._revoke(payload["jti"], payload["exp"])

    async def _revoke(self, jti: str, exp: int) -> None:
        ttl = max(int(exp - datetime.now(UTC).timestamp()), 1)
        await self.redis.set(redis_keys.revoked_jti(jti), "1", ex=ttl)
