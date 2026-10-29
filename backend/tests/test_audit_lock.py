from sqlalchemy.dialects import postgresql

from app.repositories.audit import AuditRepository


class _Capture:
    sql = None

    async def execute(self, stmt):
        _Capture.sql = str(stmt.compile(dialect=postgresql.dialect()))


async def test_audit_chain_lock_does_not_conflict_with_fk_share_locks():
    """Regression: FOR UPDATE here deadlocked under concurrent load (found by a k6 run on PostgreSQL)."""
    import uuid
    await AuditRepository(_Capture()).lock_chain(uuid.uuid4())
    assert "FOR NO KEY UPDATE" in _Capture.sql
    assert "FOR UPDATE" not in _Capture.sql.replace("FOR NO KEY UPDATE", "")
