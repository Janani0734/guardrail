import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ApprovalStatus
from app.schemas.common import ORMModel


class ApprovalOut(ORMModel):
    id: uuid.UUID
    action_request_id: uuid.UUID
    action_id: str
    agent_slug: str
    tool: str
    environment: str
    estimated_cost: Decimal
    arguments: dict[str, Any]
    reason: str | None
    message: str | None
    status: ApprovalStatus
    expires_at: datetime
    policy_id: uuid.UUID | None = None
    policy_name: str | None = None
    decided_by: uuid.UUID | None = None
    decided_by_email: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    created_at: datetime


class DecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
