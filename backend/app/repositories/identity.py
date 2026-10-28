from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership, Organization, User
from app.models.enums import Role


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return (await self.session.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()

    def add(self, user: User) -> User:
        self.session.add(user)
        return user


class OrganizationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID) -> Organization | None:
        return await self.session.get(Organization, org_id)

    async def slug_exists(self, slug: str) -> bool:
        return (await self.session.execute(select(Organization.id).where(Organization.slug == slug))).first() is not None

    def add(self, org: Organization) -> Organization:
        self.session.add(org)
        return org


class MembershipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        stmt = select(Membership).where(Membership.organization_id == org_id, Membership.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def first_for_user(self, user_id: uuid.UUID) -> Membership | None:
        stmt = select(Membership).where(Membership.user_id == user_id).order_by(Membership.created_at).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_org(self, org_id: uuid.UUID) -> list[Membership]:
        stmt = select(Membership).where(Membership.organization_id == org_id).order_by(Membership.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_admins(self, org_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Membership).where(
            Membership.organization_id == org_id, Membership.role == Role.ADMIN
        )
        return (await self.session.execute(stmt)).scalar_one()

    def add(self, membership: Membership) -> Membership:
        self.session.add(membership)
        return membership
