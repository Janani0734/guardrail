import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, Forbidden, NotFound
from app.core.security import hash_password
from app.models import Membership, Organization, User
from app.models.enums import ActorType, Role
from app.repositories.identity import MembershipRepository, OrganizationRepository, UserRepository
from app.schemas.admin import MemberCreate, MemberOut
from app.services.audit_service import AuditService
from app.services.principal import Principal


def _member_out(m: Membership) -> MemberOut:
    return MemberOut(user_id=m.user_id, email=m.user.email, full_name=m.user.full_name, role=m.role,
                     is_active=m.user.is_active, created_at=m.created_at)


class MemberService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.orgs = OrganizationRepository(session)
        self.memberships = MembershipRepository(session)
        self.audit = AuditService(session)

    def _actor(self, p: Principal) -> dict[str, Any]:
        return {"actor_type": ActorType.USER, "actor_id": p.user_id, "actor_label": p.email}

    async def organization(self, p: Principal) -> Organization:
        org = await self.orgs.get(p.org_id)
        if not org:
            raise NotFound("Organization not found", code="ORG_NOT_FOUND")
        return org

    async def rename(self, p: Principal, name: str) -> Organization:
        org = await self.organization(p)
        old, org.name = org.name, name
        await self.audit.log(org_id=p.org_id, event_type="ORGANIZATION_UPDATED", entity_type="organization",
                             entity_id=org.id, details={"from": old, "to": name}, **self._actor(p))
        await self.session.commit()
        return org

    async def list(self, p: Principal) -> list[MemberOut]:
        return [_member_out(m) for m in await self.memberships.list_for_org(p.org_id)]

    async def create(self, p: Principal, data: MemberCreate) -> MemberOut:
        email = data.email.lower()
        user = await self.users.get_by_email(email)
        if user:
            if await self.memberships.get(p.org_id, user.id):
                raise Conflict("User is already a member of this organization", code="ALREADY_MEMBER")
        else:
            user = self.users.add(User(email=email, password_hash=hash_password(data.password), full_name=data.full_name))
            await self.session.flush()
        m = self.memberships.add(Membership(organization_id=p.org_id, user_id=user.id, role=data.role))
        await self.session.flush()
        await self.audit.log(org_id=p.org_id, event_type="MEMBER_ADDED", entity_type="user", entity_id=user.id,
                             details={"email": email, "role": data.role.value}, **self._actor(p))
        await self.session.commit()
        await self.session.refresh(m)
        return _member_out(m)

    async def set_role(self, p: Principal, user_id: uuid.UUID, role: Role) -> MemberOut:
        m = await self.memberships.get(p.org_id, user_id)
        if not m:
            raise NotFound("Member not found", code="MEMBER_NOT_FOUND")
        if m.role == Role.ADMIN and role != Role.ADMIN and await self.memberships.count_admins(p.org_id) <= 1:
            raise Forbidden("An organization needs at least one admin", code="LAST_ADMIN")
        old, m.role = m.role, role
        await self.audit.log(org_id=p.org_id, event_type="MEMBER_ROLE_CHANGED", entity_type="user", entity_id=user_id,
                             details={"from": old.value, "to": role.value}, **self._actor(p))
        await self.session.commit()
        return _member_out(m)

    async def remove(self, p: Principal, user_id: uuid.UUID) -> None:
        m = await self.memberships.get(p.org_id, user_id)
        if not m:
            raise NotFound("Member not found", code="MEMBER_NOT_FOUND")
        if m.role == Role.ADMIN and await self.memberships.count_admins(p.org_id) <= 1:
            raise Forbidden("An organization needs at least one admin", code="LAST_ADMIN")
        await self.session.delete(m)
        await self.audit.log(org_id=p.org_id, event_type="MEMBER_REMOVED", entity_type="user", entity_id=user_id,
                             details={"email": m.user.email}, **self._actor(p))
        await self.session.commit()
