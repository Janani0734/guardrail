import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, UTCDateTime, enum_col
from app.models.enums import ActionOutcome, ActionStatus, ActorType, ApprovalStatus, Decision


class ActionRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "action_requests"
    __table_args__ = (
        UniqueConstraint("organization_id", "agent_id", "action_id", name="uq_action_requests_org_agent_action"),
        Index("ix_action_requests_org_created", "organization_id", "created_at"),
        Index("ix_action_requests_agent_id", "agent_id"),
        Index("ix_action_requests_action_id", "action_id"),
        Index("ix_action_requests_status", "status"),
        Index("ix_action_requests_environment", "environment"),
        Index("ix_action_requests_tool", "tool"),
        Index("ix_action_requests_created_at", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    action_id: Mapped[str] = mapped_column(String(128), nullable=False)  # client-supplied idempotency id
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)  # already redacted
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    secrets_redacted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[Decision] = mapped_column(enum_col(Decision), nullable=False)
    status: Mapped[ActionStatus] = mapped_column(enum_col(ActionStatus), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[ActionOutcome | None] = mapped_column(enum_col(ActionOutcome), nullable=True)
    outcome_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PolicyDecision(IdMixin, TimestampMixin, Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint("action_request_id", name="uq_policy_decisions_action_request"),
        Index("ix_policy_decisions_org_created", "organization_id", "created_at"),
        Index("ix_policy_decisions_policy_id", "policy_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    action_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action_requests.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    decision: Mapped[Decision] = mapped_column(enum_col(Decision), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    trace: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)


class Approval(IdMixin, TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("action_request_id", name="uq_approvals_action_request"),
        Index("ix_approvals_org_status", "organization_id", "status"),
        Index("ix_approvals_status_expires", "status", "expires_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    action_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action_requests.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[ApprovalStatus] = mapped_column(enum_col(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AuditLog(IdMixin, TimestampMixin, Base):
    """Append-only, hash-chained per organization. UPDATE/DELETE are rejected in the ORM and by a Postgres trigger."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        UniqueConstraint("organization_id", "seq", name="uq_audit_logs_org_seq"),
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(enum_col(ActorType), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(254), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RateLimitEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "rate_limit_events"
    __table_args__ = (
        Index("ix_rate_limit_events_org_created", "organization_id", "created_at"),
        Index("ix_rate_limit_events_agent_id", "agent_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    observed: Mapped[int] = mapped_column(Integer, nullable=False)


class ImmutableAuditError(RuntimeError):
    pass


@event.listens_for(AuditLog, "before_update")
def _block_audit_update(*_: Any) -> None:
    raise ImmutableAuditError("audit_logs rows are immutable")


@event.listens_for(AuditLog, "before_delete")
def _block_audit_delete(*_: Any) -> None:
    raise ImmutableAuditError("audit_logs rows cannot be deleted")
