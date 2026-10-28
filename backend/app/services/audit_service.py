"""Append-only, hash-chained audit log.

entry_hash = SHA-256(canonical_json({seq, org, actor, event, entity, details, created_at, prev_hash})).
Each entry therefore commits to its predecessor; editing or deleting any historical row breaks every later hash,
which `verify_chain` detects. A Postgres trigger (see the initial migration) additionally rejects UPDATE/DELETE.
"""
import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.models.base import utcnow
from app.models.enums import ActorType
from app.repositories.audit import AuditRepository

GENESIS_HASH = "0" * 64


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda o: str(o) if isinstance(o, (Decimal, uuid.UUID)) else (
        o.isoformat() if isinstance(o, datetime) else str(o)), sort_keys=True))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def compute_hash(entry: AuditLog) -> str:
    payload = {
        "seq": entry.seq, "org": str(entry.organization_id), "actor_type": entry.actor_type.value
        if hasattr(entry.actor_type, "value") else entry.actor_type,
        "actor_id": entry.actor_id, "actor_label": entry.actor_label, "event_type": entry.event_type,
        "entity_type": entry.entity_type, "entity_id": entry.entity_id, "details": entry.details,
        "created_at": _iso(entry.created_at), "prev_hash": entry.prev_hash,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = AuditRepository(session)

    async def log(
        self, *, org_id: uuid.UUID, actor_type: ActorType, event_type: str, entity_type: str,
        entity_id: str | uuid.UUID | None = None, actor_id: str | uuid.UUID | None = None,
        actor_label: str | None = None, details: dict[str, Any] | None = None, created_at: datetime | None = None,
    ) -> AuditLog:
        await self.repo.lock_chain(org_id)
        last = await self.repo.last(org_id)
        entry = AuditLog(
            organization_id=org_id, seq=(last.seq + 1) if last else 1, actor_type=actor_type,
            actor_id=str(actor_id) if actor_id else None, actor_label=actor_label, event_type=event_type,
            entity_type=entity_type, entity_id=str(entity_id) if entity_id else None,
            details=_json_safe(details or {}), prev_hash=last.entry_hash if last else GENESIS_HASH,
            created_at=created_at or utcnow(),
        )
        entry.updated_at = entry.created_at
        entry.entry_hash = compute_hash(entry)
        self.repo.add(entry)
        await self.session.flush()
        return entry

    async def verify_chain(self, org_id: uuid.UUID) -> tuple[bool, int, int | None]:
        prev = GENESIS_HASH
        expected_seq = 1
        checked = 0
        async for entry in self.repo.iter_chain(org_id):
            checked += 1
            if entry.seq != expected_seq or entry.prev_hash != prev or compute_hash(entry) != entry.entry_hash:
                return False, checked, entry.seq
            prev = entry.entry_hash
            expected_seq += 1
        return True, checked, None
