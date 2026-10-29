import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import ActionOutcome, ActionStatus, ApprovalStatus, Decision
from app.schemas.common import ORMModel

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$"
MAX_ARGUMENT_BYTES = 64 * 1024


class EvaluateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80, examples=["support-agent-01"])
    action_id: str = Field(pattern=ID_PATTERN, examples=["act_123"])
    tool: str = Field(pattern=ID_PATTERN, examples=["delete_database_records"])
    environment: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$", examples=["production"])
    arguments: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1000000000"))
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("environment")
    @classmethod
    def lower_env(cls, v: str) -> str:
        return v.lower()

    @field_validator("arguments")
    @classmethod
    def limit_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, default=str)) > MAX_ARGUMENT_BYTES:
            raise ValueError("arguments exceeds 64 KB")
        return v


class AllowResponse(BaseModel):
    decision: Decision = Decision.ALLOW
    action_id: str
    policy_id: str | None = None
    expires_at: datetime | None = None


class BlockResponse(BaseModel):
    decision: Decision = Decision.BLOCK
    action_id: str
    reason_code: str
    message: str | None = None
    policy_id: str | None = None


class ApprovalRequiredResponse(BaseModel):
    decision: Decision = Decision.REQUIRE_APPROVAL
    action_id: str
    approval_id: str
    expires_at: datetime
    message: str | None = None
    policy_id: str | None = None


class OutcomeRequest(BaseModel):
    outcome: ActionOutcome
    detail: str | None = Field(default=None, max_length=500)


class ActionStatusResponse(BaseModel):
    action_id: str
    decision: Decision
    status: ActionStatus
    approval_id: str | None = None
    approval_status: ApprovalStatus | None = None
    expires_at: datetime | None = None
    decision_reason: str | None = None
    approval_token: str | None = Field(default=None, description="Returned once, only after approval")


class VerifyTokenRequest(BaseModel):
    """`token` alone keeps the original behaviour (agent-bound, one-time, expiring).

    A trusted executor also sends `action_id`, `tool`, `environment` and `arguments`; the token is then valid only if
    they are exactly what the approver saw. `tool`, `environment` and `arguments` must be sent together."""

    token: str = Field(min_length=8, max_length=200)
    action_id: str | None = Field(default=None, pattern=ID_PATTERN)
    tool: str | None = Field(default=None, pattern=ID_PATTERN)
    environment: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,32}$")
    arguments: dict[str, Any] | None = None

    @model_validator(mode="after")
    def binding_is_all_or_nothing(self) -> "VerifyTokenRequest":
        given = [self.tool is not None, self.environment is not None, self.arguments is not None]
        if any(given) and not all(given):
            raise ValueError("tool, environment and arguments must be provided together")
        return self

    @property
    def binds_request(self) -> bool:
        return self.tool is not None


class VerifyTokenResponse(BaseModel):
    valid: bool
    action_id: str | None = None
    approval_id: str | None = None
    reason: str | None = Field(default=None, description="Why a token was refused (only when valid is false)")


class ActionHistoryOut(ORMModel):
    id: uuid.UUID
    action_id: str
    agent_id: uuid.UUID
    agent_slug: str
    tool: str
    environment: str
    arguments: dict[str, Any]
    estimated_cost: Decimal
    reason: str | None
    decision: Decision
    status: ActionStatus
    reason_code: str | None
    outcome: ActionOutcome | None
    secrets_redacted: int
    policy_id: uuid.UUID | None = None
    policy_name: str | None = None
    message: str | None = None
    approval_id: uuid.UUID | None = None
    created_at: datetime


class ActionDetailOut(ActionHistoryOut):
    trace: list[dict[str, Any]] = []
    latency_ms: int | None = None
