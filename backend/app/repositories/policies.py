from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Policy
from app.models.enums import Decision, PolicyType
from app.repositories.common import paginate


class PolicyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID, policy_id: uuid.UUID) -> Policy | None:
        stmt = select(Policy).where(Policy.id == policy_id, Policy.organization_id == org_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, org_id: uuid.UUID, name: str) -> Policy | None:
        stmt = select(Policy).where(Policy.organization_id == org_id, Policy.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active(self, org_id: uuid.UUID) -> list[Policy]:
        stmt = (
            select(Policy)
            .where(Policy.organization_id == org_id, Policy.is_active.is_(True))
            .order_by(Policy.priority, Policy.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list(
        self, org_id: uuid.UUID, page: int, page_size: int, policy_type: PolicyType | None,
        effect: Decision | None, is_active: bool | None, search: str | None,
    ):
        stmt = select(Policy).where(Policy.organization_id == org_id)
        if policy_type:
            stmt = stmt.where(Policy.policy_type == policy_type)
        if effect:
            stmt = stmt.where(Policy.effect == effect)
        if is_active is not None:
            stmt = stmt.where(Policy.is_active == is_active)
        if search:
            stmt = stmt.where(Policy.name.ilike(f"%{search.lower()}%"))
        rows, total = await paginate(self.session, stmt.order_by(Policy.priority, Policy.created_at), page, page_size)
        return [r[0] for r in rows], total

    def add(self, policy: Policy) -> Policy:
        self.session.add(policy)
        return policy

    async def delete(self, policy: Policy) -> None:
        await self.session.delete(policy)
