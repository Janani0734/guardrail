"""Approval-expiry background worker.

Runs either embedded in the API process (WORKER_ENABLED=true) or standalone:  python -m app.workers.expiry
A Redis lock (SET NX EX) coordinates multiple instances so only one sweeps at a time; correctness does not depend on
it (rows are claimed with FOR UPDATE SKIP LOCKED) - the lock just avoids wasted work.
"""
import asyncio
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import configure_logging, get_logger
from app.core.redis import get_redis_client
from app.services.approval_service import ApprovalService
from app.utils.redis_keys import EXPIRY_LOCK

log = get_logger(__name__)


async def run_once(redis: Redis | None = None, lock_ttl: int = 30) -> int:
    redis = redis or get_redis_client()
    token = uuid.uuid4().hex
    try:
        got = await redis.set(EXPIRY_LOCK, token, nx=True, ex=lock_ttl)
    except RedisError:
        log.warning("expiry worker cannot reach redis; skipping sweep")
        return 0
    if not got:
        return 0
    try:
        async with get_sessionmaker()() as session:
            count = await ApprovalService(session, redis).expire_due()
        if count:
            log.info("expired %s pending approvals", count)
        return count
    finally:
        try:  # release only our own lock
            if await redis.get(EXPIRY_LOCK) == token:
                await redis.delete(EXPIRY_LOCK)
        except RedisError:
            pass


async def run_forever(stop: asyncio.Event | None = None) -> None:
    interval = get_settings().worker_interval_seconds
    stop = stop or asyncio.Event()
    log.info("approval expiry worker started (interval=%ss)", interval)
    while not stop.is_set():
        try:
            await run_once()
        except Exception:
            log.exception("expiry sweep failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_forever())
