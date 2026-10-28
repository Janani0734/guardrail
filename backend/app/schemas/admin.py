import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import ActorType, Role
from app.schemas.common import ORMModel


class AuditLogOut(ORMModel):
    id: uuid.UUID
    seq: int
    actor_type: ActorType
    actor_id: str | None
    actor_label: str | None
    event_type: str
    entity_type: str
    entity_id: str | None
    details: dict[str, Any]
    prev_hash: str
    entry_hash: str
    created_at: datetime


class AuditVerifyOut(BaseModel):
    valid: bool
    checked: int
    first_invalid_seq: int | None = None


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class MemberCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: Role = Role.VIEWER


class MemberRoleUpdate(BaseModel):
    role: Role


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
