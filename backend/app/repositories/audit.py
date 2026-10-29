from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Organization
from app.repositories.common import paginate


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_chain(self, org_id: uuid.UUID) -> None:
        """Serialise appenders per organisation so (seq, prev_hash) is always consistent.

        FOR NO KEY UPDATE, not FOR UPDATE: earlier statements in the same transaction insert rows that reference the
        organisation, which takes a FOR KEY SHARE lock on it. Upgrading that to a full FOR UPDATE makes two concurrent
        requests wait for each other's share lock (PostgreSQL deadlock). NO KEY UPDATE does not conflict with KEY SHARE
        but still conflicts with other appenders, so the chain stays strictly serialised."""
        stmt = select(Organization.id).where(Organization.id == org_id).with_for_update(key_share=True)
        await self.session.execute(stmt)

    async def last(self, org_id: uuid.UUID) -> AuditLog | None:
        stmt = select(AuditLog).where(AuditLog.organization_id == org_id).order_by(AuditLog.seq.desc()).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    def add(self, entry: AuditLog) -> AuditLog:
        self.session.add(entry)
        return entry

    async def list(
        self, org_id: uuid.UUID, page: int, page_size: int, *, event_type: str | None = None,
        entity_type: str | None = None, entity_id: str | None = None, actor_type: str | None = None,
        date_from: datetime | None = None, date_to: datetime | None = None, order: str = "desc",
    ):
        stmt = select(AuditLog).where(AuditLog.organization_id == org_id)
        if event_type:
            stmt = stmt.where(AuditLog.event_type == event_type)
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if actor_type:
            stmt = stmt.where(AuditLog.actor_type == actor_type)
        if date_from:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLog.created_at <= date_to)
        stmt = stmt.order_by(AuditLog.seq.asc() if order == "asc" else AuditLog.seq.desc())
        rows, total = await paginate(self.session, stmt, page, page_size)
        return [r[0] for r in rows], total

    async def iter_chain(self, org_id: uuid.UUID, batch: int = 500):
        offset = 0
        while True:
            stmt = (
                select(AuditLog).where(AuditLog.organization_id == org_id)
                .order_by(AuditLog.seq).limit(batch).offset(offset)
            )
            rows = list((await self.session.execute(stmt)).scalars().all())
            if not rows:
                return
            for r in rows:
                yield r
            offset += batch
