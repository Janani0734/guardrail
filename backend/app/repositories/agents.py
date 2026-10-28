from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentTool, ApiKey, Tool
from app.models.enums import AgentStatus
from app.repositories.common import paginate


class AgentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID, agent_id: uuid.UUID) -> Agent | None:
        stmt = select(Agent).where(Agent.id == agent_id, Agent.organization_id == org_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, org_id: uuid.UUID, slug: str) -> Agent | None:
        stmt = select(Agent).where(Agent.slug == slug, Agent.organization_id == org_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(self, org_id: uuid.UUID, page: int, page_size: int, search: str | None, status: AgentStatus | None):
        stmt = select(Agent).where(Agent.organization_id == org_id)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(Agent.slug.ilike(like) | Agent.name.ilike(like))
        if status:
            stmt = stmt.where(Agent.status == status)
        rows, total = await paginate(self.session, stmt.order_by(Agent.created_at.desc()), page, page_size)
        return [r[0] for r in rows], total

    def add(self, agent: Agent) -> Agent:
        self.session.add(agent)
        return agent


class ApiKeyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == org_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_hash(self, key_hash: str) -> tuple[ApiKey, Agent] | None:
        stmt = select(ApiKey, Agent).join(Agent, Agent.id == ApiKey.agent_id).where(ApiKey.key_hash == key_hash)
        row = (await self.session.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def list(self, org_id: uuid.UUID, page: int, page_size: int, agent_id: uuid.UUID | None, active_only: bool):
        stmt = (
            select(ApiKey, Agent.slug, Agent.name)
            .join(Agent, Agent.id == ApiKey.agent_id)
            .where(ApiKey.organization_id == org_id)
        )
        if agent_id:
            stmt = stmt.where(ApiKey.agent_id == agent_id)
        if active_only:
            stmt = stmt.where(ApiKey.revoked_at.is_(None))
        return await paginate(self.session, stmt.order_by(ApiKey.created_at.desc()), page, page_size)

    def add(self, key: ApiKey) -> ApiKey:
        self.session.add(key)
        return key

    async def touch(self, key: ApiKey, when: datetime) -> None:
        key.last_used_at = when


class ToolRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID, tool_id: uuid.UUID) -> Tool | None:
        stmt = select(Tool).where(Tool.id == tool_id, Tool.organization_id == org_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, org_id: uuid.UUID, name: str) -> Tool | None:
        stmt = select(Tool).where(Tool.organization_id == org_id, Tool.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_many(self, org_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Tool]:
        if not ids:
            return []
        stmt = select(Tool).where(Tool.organization_id == org_id, Tool.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list(self, org_id: uuid.UUID, page: int, page_size: int, search: str | None):
        stmt = select(Tool).where(Tool.organization_id == org_id)
        if search:
            stmt = stmt.where(Tool.name.ilike(f"%{search.lower()}%"))
        rows, total = await paginate(self.session, stmt.order_by(Tool.name), page, page_size)
        return [r[0] for r in rows], total

    async def list_for_agent(self, org_id: uuid.UUID, agent_id: uuid.UUID) -> list[Tool]:
        stmt = (
            select(Tool)
            .join(AgentTool, AgentTool.tool_id == Tool.id)
            .where(AgentTool.agent_id == agent_id, Tool.organization_id == org_id)
            .order_by(Tool.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def is_assigned(self, agent_id: uuid.UUID, tool_id: uuid.UUID) -> bool:
        stmt = select(AgentTool.id).where(AgentTool.agent_id == agent_id, AgentTool.tool_id == tool_id)
        return (await self.session.execute(stmt)).first() is not None

    async def set_agent_tools(self, agent_id: uuid.UUID, tool_ids: list[uuid.UUID]) -> None:
        await self.session.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
        for tid in dict.fromkeys(tool_ids):
            self.session.add(AgentTool(agent_id=agent_id, tool_id=tid))
        await self.session.flush()

    def add(self, tool: Tool) -> Tool:
        self.session.add(tool)
        return tool
