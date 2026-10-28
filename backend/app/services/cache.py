import uuid

from redis.asyncio import Redis

from app.core.logging import get_logger
from app.utils import redis_keys

log = get_logger(__name__)


async def bump_analytics_version(redis: Redis, org_id: uuid.UUID) -> None:
    """O(1) cache invalidation: cached dashboards embed the version in their key, so a bump orphans them."""
    try:
        await redis.incr(redis_keys.analytics_version(org_id))
    except Exception:  # cache invalidation must never fail a request
        log.warning("analytics version bump failed", exc_info=True)
