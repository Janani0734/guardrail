import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import IdMixin, JSONType, TimestampMixin, enum_col
from app.models.enums import Decision, PolicyType, RuleOperator


class Policy(IdMixin, TimestampMixin, Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_policies_org_name"),
        Index("ix_policies_org_active_priority", "organization_id", "is_active", "priority"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_type: Mapped[PolicyType] = mapped_column(enum_col(PolicyType), nullable=False, default=PolicyType.RULE)
    effect: Mapped[Decision] = mapped_column(enum_col(Decision), nullable=False, default=Decision.BLOCK)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)  # lower number = evaluated first
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, default="POLICY_MATCH")
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    rules: Mapped[list["PolicyRule"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan", order_by="PolicyRule.position", lazy="selectin"
    )


class PolicyRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "policy_rules"
    __table_args__ = (Index("ix_policy_rules_policy_id", "policy_id"),)

    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("policies.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    field: Mapped[str] = mapped_column(String(80), nullable=False)
    operator: Mapped[RuleOperator] = mapped_column(enum_col(RuleOperator), nullable=False)
    value: Mapped[Any] = mapped_column(JSONType, nullable=False)

    policy: Mapped[Policy] = relationship(back_populates="rules")
