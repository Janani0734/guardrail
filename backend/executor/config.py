"""Executor settings (environment variables). Nothing here is secret: agents bring their own GuardRail API key."""
from functools import lru_cache

from pydantic_settings import BaseSettings


class ExecutorSettings(BaseSettings):
    guardrail_url: str = "http://localhost:8000"
    redis_url: str = "redis://localhost:6379/0"
    guardrail_timeout_seconds: float = 5.0
    default_wait_seconds: float = 30.0   # how long one call waits for an admin before answering 202
    max_wait_seconds: float = 120.0
    poll_interval_seconds: float = 1.0
    record_ttl_seconds: int = 86400      # how long a finished execution is remembered (exactly-once window)
    running_ttl_seconds: int = 120       # a crashed executor frees its claim after this long


@lru_cache
def get_settings() -> ExecutorSettings:
    return ExecutorSettings()
