import uuid

from fastapi import APIRouter, Query, status

from app.models.enums import AgentStatus
from app.routers.deps import Manager, SessionDep, Viewer
from app.schemas.agents import (
    AgentCreate, AgentOut, AgentToolsUpdate, AgentUpdate, ApiKeyCreate, ApiKeyCreated, ApiKeyListItem, ApiKeyOut,
    ToolCreate, ToolOut, ToolUpdate,
)
from app.schemas.common import Page
from app.services.agent_service import AgentService

router = APIRouter(prefix="/v1", tags=["agents"])
PageQ = Query(1, ge=1)
SizeQ = Query(20, ge=1, le=100)


@router.get("/agents", response_model=Page[AgentOut])
async def list_agents(p: Viewer, session: SessionDep, page: int = PageQ, page_size: int = SizeQ,
                      search: str | None = Query(None, max_length=80), status: AgentStatus | None = None):
    items, total = await AgentService(session).list_agents(p, page, page_size, search, status)
    return Page.build([AgentOut.model_validate(a) for a in items], total, page, page_size)


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(data: AgentCreate, p: Manager, session: SessionDep):
    return await AgentService(session).create_agent(p, data)


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, p: Viewer, session: SessionDep):
    return await AgentService(session).get_agent(p, agent_id)


@router.patch("/agents/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: uuid.UUID, data: AgentUpdate, p: Manager, session: SessionDep):
    return await AgentService(session).update_agent(p, agent_id, data)


@router.get("/agents/{agent_id}/tools", response_model=list[ToolOut])
async def agent_tools(agent_id: uuid.UUID, p: Viewer, session: SessionDep):
    return await AgentService(session).agent_tools(p, agent_id)


@router.put("/agents/{agent_id}/tools", response_model=list[ToolOut])
async def set_agent_tools(agent_id: uuid.UUID, data: AgentToolsUpdate, p: Manager, session: SessionDep):
    return await AgentService(session).set_agent_tools(p, agent_id, data.tool_ids)


@router.post("/agents/{agent_id}/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(agent_id: uuid.UUID, data: ApiKeyCreate, p: Manager, session: SessionDep):
    return await AgentService(session).create_key(p, agent_id, data)


@router.get("/api-keys", response_model=Page[ApiKeyListItem])
async def list_api_keys(p: Viewer, session: SessionDep, page: int = PageQ, page_size: int = SizeQ,
                        agent_id: uuid.UUID | None = None, active_only: bool = False):
    return await AgentService(session).list_keys(p, page, page_size, agent_id, active_only)


@router.delete("/api-keys/{key_id}", response_model=ApiKeyOut)
async def revoke_api_key(key_id: uuid.UUID, p: Manager, session: SessionDep):
    return await AgentService(session).revoke_key(p, key_id)


@router.get("/tools", response_model=Page[ToolOut])
async def list_tools(p: Viewer, session: SessionDep, page: int = PageQ, page_size: int = Query(20, ge=1, le=200),
                     search: str | None = Query(None, max_length=80)):
    items, total = await AgentService(session).list_tools(p, page, page_size, search)
    return Page.build([ToolOut.model_validate(t) for t in items], total, page, page_size)


@router.post("/tools", response_model=ToolOut, status_code=status.HTTP_201_CREATED)
async def create_tool(data: ToolCreate, p: Manager, session: SessionDep):
    return await AgentService(session).create_tool(p, data)


@router.patch("/tools/{tool_id}", response_model=ToolOut)
async def update_tool(tool_id: uuid.UUID, data: ToolUpdate, p: Manager, session: SessionDep):
    return await AgentService(session).update_tool(p, tool_id, data)
