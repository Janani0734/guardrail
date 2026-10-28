import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.analytics import AnalyticsRepository
from app.utils import redis_keys


def _fill(points: list[dict[str, Any]], since: datetime, now: datetime, hourly: bool) -> list[dict[str, Any]]:
    by_bucket = {p["bucket"]: p for p in points}
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    cur = since.replace(minute=0, second=0, microsecond=0) if hourly else since.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    while cur <= now:
        key = cur.strftime("%Y-%m-%dT%H:00") if hourly else cur.strftime("%Y-%m-%d")
        out.append(by_bucket.get(key, {"bucket": key, "total": 0, "allowed": 0, "blocked": 0, "approvals": 0}))
        cur += step
    return out


class AnalyticsService:
    def __init__(self, session: AsyncSession, redis: Redis):
        self.session = session
        self.redis = redis
        self.repo = AnalyticsRepository(session)
        self.ttl = get_settings().analytics_cache_ttl_seconds

    async def overview(self, org_id: uuid.UUID, days: int) -> dict[str, Any]:
        cache_key = None
        try:
            version = await self.redis.get(redis_keys.analytics_version(org_id)) or "0"
            cache_key = redis_keys.analytics_cache(org_id, version, "overview", days)
            cached = await self.redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                data["cached"] = True
                return data
        except RedisError:
            cache_key = None
        data = await self._compute(org_id, days)
        if cache_key:
            try:
                await self.redis.set(cache_key, json.dumps(data), ex=self.ttl)
            except RedisError:
                pass
        data["cached"] = False
        return data

    async def _compute(self, org_id: uuid.UUID, days: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        since = now - timedelta(days=days)
        totals = await self.repo.totals(org_id, since)
        approvals = await self.repo.approval_counts(org_id, since)
        hourly = days <= 2
        series = await self.repo.timeseries(org_id, since, "hour" if hourly else "day")
        return {
            "days": days,
            "totals": {
                **totals,
                "block_rate": round(totals["blocked"] / totals["total"], 4) if totals["total"] else 0.0,
                "pending_approvals": await self.repo.pending_now(org_id),
                "rate_limited": await self.repo.rate_limit_events(org_id, since),
            },
            "approvals": approvals,
            "timeseries": _fill(series, since, now, hourly),
            "agent_activity": await self.repo.agent_activity(org_id, since),
            "top_tools": await self.repo.top_tools(org_id, since),
            "block_reasons": await self.repo.top_reason_codes(org_id, since),
            "generated_at": now.isoformat(),
        }
