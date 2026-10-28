import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Decision, PolicyType, RuleOperator
from app.schemas.common import ORMModel

REASON_CODE_PATTERN = r"^[A-Z0-9_]{2,64}$"


class RuleIn(BaseModel):
    field: str = Field(min_length=1, max_length=80, description="tool | environment | estimated_cost | reason | agent_id | arguments_text | arguments.<path>")
    operator: RuleOperator
    value: Any


class RuleOut(ORMModel):
    id: uuid.UUID
    position: int
    field: str
    operator: RuleOperator
    value: Any


class PolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    policy_type: PolicyType = PolicyType.RULE
    effect: Decision = Decision.BLOCK
    priority: int = Field(default=100, ge=0, le=100000)
    is_active: bool = True
    reason_code: str = Field(default="POLICY_MATCH", pattern=REASON_CODE_PATTERN)
    message: str | None = Field(default=None, max_length=500)
    config: dict[str, Any] = Field(default_factory=dict)
    rules: list[RuleIn] = Field(default_factory=list, max_length=25)


class PolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    effect: Decision | None = None
    priority: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    reason_code: str | None = Field(default=None, pattern=REASON_CODE_PATTERN)
    message: str | None = Field(default=None, max_length=500)
    config: dict[str, Any] | None = None
    rules: list[RuleIn] | None = Field(default=None, max_length=25)


class PolicyOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    policy_type: PolicyType
    effect: Decision
    priority: int
    is_active: bool
    reason_code: str
    message: str | None
    config: dict[str, Any]
    rules: list[RuleOut]
    created_at: datetime
    updated_at: datetime


class SimulateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    tool: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="production", max_length=32)
    arguments: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: float = Field(default=0, ge=0)
    reason: str | None = Field(default=None, max_length=2000)


class SimulateResponse(BaseModel):
    decision: Decision
    reason_code: str
    message: str | None
    policy_id: uuid.UUID | None
    policy_name: str | None
    tool_known: bool
    tool_permitted: bool
    trace: list[dict[str, Any]]
    note: str = "Simulation only: nothing was persisted and rate limits / repeat counters were not touched."
