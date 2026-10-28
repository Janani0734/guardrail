"""Redis-backed protections: sliding-window rate limiting and repeated-failure tracking.

Redis is deliberately NOT the source of truth: counters are ephemeral safety state with TTLs.
Every decision that matters (including rate-limit denials) is also written to PostgreSQL.
"""
import math
import time
import uuid

from redis.asyncio import Redis

from app.utils import redis_keys


class RateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """Sliding-window log. Returns (allowed, count_in_window, retry_after_seconds).

        MULTI/EXEC keeps trim + add + count atomic, so concurrent requests can't both slip under the limit.
        Rejected attempts are also recorded, which deliberately penalises clients that hammer a closed gate.
        """
        now = time.time()
        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"
        pipe = self.redis.pipeline(transaction=True)
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds + 1)
        _, _, count, _ = await pipe.execute()
        if count <= limit:
            return True, int(count), 0
        oldest = await self.redis.zrange(key, 0, 0, withscores=True)
        retry = 1
        if oldest:
            retry = max(1, math.ceil(oldest[0][1] + window_seconds - now))
        return False, int(count), retry


class RepeatTracker:
    """Counts identical blocked/failed actions; after N inside a window the fingerprint is temporarily blocked."""

    def __init__(self, redis: Redis):
        self.redis = redis

    async def blocked_ttl(self, org_id: uuid.UUID, agent_id: uuid.UUID, fp: str) -> int:
        ttl = await self.redis.ttl(redis_keys.temp_block(org_id, agent_id, fp))
        return ttl if ttl and ttl > 0 else 0

    async def record_failure(
        self, org_id: uuid.UUID, agent_id: uuid.UUID, fp: str, *, threshold: int, window_seconds: int,
        block_seconds: int,
    ) -> bool:
        """Returns True when this failure tripped the temporary block."""
        key = redis_keys.repeat_counter(org_id, agent_id, fp)
        pipe = self.redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = await pipe.execute()
        if int(count) >= threshold:
            pipe = self.redis.pipeline(transaction=True)
            pipe.set(redis_keys.temp_block(org_id, agent_id, fp), "1", ex=block_seconds)
            pipe.delete(key)
            await pipe.execute()
            return True
        return False
