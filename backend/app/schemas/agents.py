import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AgentStatus, RiskLevel
from app.schemas.common import ORMModel

SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,78}[a-z0-9]$"
TOOL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


class AgentCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN, description="Identifier agents send as agent_id, e.g. support-agent-01")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: AgentStatus | None = None


class AgentOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    status: AgentStatus
    created_at: datetime
    updated_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None


class ApiKeyListItem(ApiKeyOut):
    agent_slug: str
    agent_name: str


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Shown exactly once. Only a keyed hash is stored.")


class ToolCreate(BaseModel):
    name: str = Field(pattern=TOOL_NAME_PATTERN)
    description: str | None = Field(default=None, max_length=2000)
    risk_level: RiskLevel = RiskLevel.LOW


class ToolUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    risk_level: RiskLevel | None = None
    is_active: bool | None = None


class ToolOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    risk_level: RiskLevel
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AgentToolsUpdate(BaseModel):
    tool_ids: list[uuid.UUID] = Field(max_length=500)
