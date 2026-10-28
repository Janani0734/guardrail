from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def set_redis_client(client: Redis | None) -> None:
    global _client
    _client = client


async def get_redis() -> Redis:
    return get_redis_client()


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
