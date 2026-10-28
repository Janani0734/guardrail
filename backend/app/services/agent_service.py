import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.security import generate_api_key
from app.models import Agent, ApiKey, Tool
from app.models.base import utcnow
from app.models.enums import ActorType, AgentStatus
from app.repositories.agents import AgentRepository, ApiKeyRepository, ToolRepository
from app.schemas.agents import (
    AgentCreate, AgentUpdate, ApiKeyCreate, ApiKeyCreated, ApiKeyListItem, ApiKeyOut, ToolCreate, ToolUpdate,
)
from app.schemas.common import Page
from app.services.audit_service import AuditService
from app.services.principal import Principal


def _actor(p: Principal) -> dict[str, Any]:
    return {"actor_type": ActorType.USER, "actor_id": p.user_id, "actor_label": p.email}


class AgentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.agents = AgentRepository(session)
        self.keys = ApiKeyRepository(session)
        self.tools = ToolRepository(session)
        self.audit = AuditService(session)

    # ---- agents
    async def get_agent(self, p: Principal, agent_id: uuid.UUID) -> Agent:
        agent = await self.agents.get(p.org_id, agent_id)
        if not agent:
            raise NotFound("Agent not found", code="AGENT_NOT_FOUND")
        return agent

    async def create_agent(self, p: Principal, data: AgentCreate) -> Agent:
        if await self.agents.get_by_slug(p.org_id, data.slug):
            raise Conflict("An agent with this slug already exists", code="AGENT_SLUG_TAKEN")
        agent = self.agents.add(Agent(organization_id=p.org_id, slug=data.slug, name=data.name,
                                      description=data.description))
        await self.session.flush()
        await self.audit.log(org_id=p.org_id, event_type="AGENT_CREATED", entity_type="agent", entity_id=agent.id,
                             details={"slug": agent.slug, "name": agent.name}, **_actor(p))
        await self.session.commit()
        return agent

    async def update_agent(self, p: Principal, agent_id: uuid.UUID, data: AgentUpdate) -> Agent:
        agent = await self.get_agent(p, agent_id)
        changes = data.model_dump(exclude_unset=True)
        for k, v in changes.items():
            setattr(agent, k, v)
        await self.audit.log(org_id=p.org_id, event_type="AGENT_UPDATED", entity_type="agent", entity_id=agent.id,
                             details={k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()}, **_actor(p))
        await self.session.commit()
        return agent

    async def list_agents(self, p: Principal, page: int, page_size: int, search: str | None,
                          status: AgentStatus | None) -> tuple[list[Agent], int]:
        return await self.agents.list(p.org_id, page, page_size, search, status)

    # ---- api keys
    async def create_key(self, p: Principal, agent_id: uuid.UUID, data: ApiKeyCreate) -> ApiKeyCreated:
        agent = await self.get_agent(p, agent_id)
        raw, prefix, key_hash = generate_api_key()
        expires = utcnow() + timedelta(days=data.expires_in_days) if data.expires_in_days else None
        key = self.keys.add(ApiKey(organization_id=p.org_id, agent_id=agent.id, name=data.name, prefix=prefix,
                                   key_hash=key_hash, created_by=p.user_id, expires_at=expires))
        await self.session.flush()
        await self.audit.log(org_id=p.org_id, event_type="API_KEY_CREATED", entity_type="api_key", entity_id=key.id,
                             details={"agent": agent.slug, "name": data.name, "prefix": prefix}, **_actor(p))
        await self.session.commit()
        return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=raw)

    async def list_keys(self, p: Principal, page: int, page_size: int, agent_id: uuid.UUID | None,
                        active_only: bool) -> Page[ApiKeyListItem]:
        if agent_id:
            await self.get_agent(p, agent_id)
        rows, total = await self.keys.list(p.org_id, page, page_size, agent_id, active_only)
        items = [ApiKeyListItem(**ApiKeyOut.model_validate(k).model_dump(), agent_slug=slug, agent_name=name)
                 for k, slug, name in rows]
        return Page.build(items, total, page, page_size)

    async def revoke_key(self, p: Principal, key_id: uuid.UUID) -> ApiKey:
        key = await self.keys.get(p.org_id, key_id)
        if not key:
            raise NotFound("API key not found", code="API_KEY_NOT_FOUND")
        if key.revoked_at is None:
            key.revoked_at = utcnow()
            await self.audit.log(org_id=p.org_id, event_type="API_KEY_REVOKED", entity_type="api_key",
                                 entity_id=key.id, details={"prefix": key.prefix}, **_actor(p))
            await self.session.commit()
        return key

    # ---- tools
    async def create_tool(self, p: Principal, data: ToolCreate) -> Tool:
        if await self.tools.get_by_name(p.org_id, data.name):
            raise Conflict("A tool with this name already exists", code="TOOL_NAME_TAKEN")
        tool = self.tools.add(Tool(organization_id=p.org_id, name=data.name, description=data.description,
                                   risk_level=data.risk_level))
        await self.session.flush()
        await self.audit.log(org_id=p.org_id, event_type="TOOL_CREATED", entity_type="tool", entity_id=tool.id,
                             details={"name": tool.name, "risk_level": tool.risk_level.value}, **_actor(p))
        await self.session.commit()
        return tool

    async def get_tool(self, p: Principal, tool_id: uuid.UUID) -> Tool:
        tool = await self.tools.get(p.org_id, tool_id)
        if not tool:
            raise NotFound("Tool not found", code="TOOL_NOT_FOUND")
        return tool

    async def update_tool(self, p: Principal, tool_id: uuid.UUID, data: ToolUpdate) -> Tool:
        tool = await self.get_tool(p, tool_id)
        changes = data.model_dump(exclude_unset=True)
        for k, v in changes.items():
            setattr(tool, k, v)
        await self.audit.log(org_id=p.org_id, event_type="TOOL_UPDATED", entity_type="tool", entity_id=tool.id,
                             details={k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()}, **_actor(p))
        await self.session.commit()
        return tool

    async def list_tools(self, p: Principal, page: int, page_size: int, search: str | None):
        return await self.tools.list(p.org_id, page, page_size, search)

    async def agent_tools(self, p: Principal, agent_id: uuid.UUID) -> list[Tool]:
        agent = await self.get_agent(p, agent_id)
        return await self.tools.list_for_agent(p.org_id, agent.id)

    async def set_agent_tools(self, p: Principal, agent_id: uuid.UUID, tool_ids: list[uuid.UUID]) -> list[Tool]:
        agent = await self.get_agent(p, agent_id)
        unique = list(dict.fromkeys(tool_ids))
        found = await self.tools.get_many(p.org_id, unique)  # org-scoped: foreign tool ids simply aren't found
        if len(found) != len(unique):
            raise ValidationFailed("One or more tools do not exist in this organization", code="UNKNOWN_TOOL_IDS")
        await self.tools.set_agent_tools(agent.id, unique)
        await self.audit.log(org_id=p.org_id, event_type="AGENT_TOOLS_UPDATED", entity_type="agent",
                             entity_id=agent.id, details={"agent": agent.slug, "tools": sorted(t.name for t in found)},
                             **_actor(p))
        await self.session.commit()
        return sorted(found, key=lambda t: t.name)
