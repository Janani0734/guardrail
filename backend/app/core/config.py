from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GuardRail"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://guardrail:guardrail@localhost:5432/guardrail"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-jwt-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    api_key_pepper: str = "dev-only-api-key-pepper-change-me-0123456789"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    bcrypt_rounds: int = 12

    approval_ttl_minutes: int = 30
    approval_token_ttl_seconds: int = 900

    default_rate_limit_per_minute: int = 60
    default_repeat_threshold: int = 3
    default_repeat_window_seconds: int = 600
    default_repeat_block_seconds: int = 300

    login_max_attempts: int = 10
    login_window_seconds: int = 300

    worker_enabled: bool = True
    worker_interval_seconds: int = 15
    analytics_cache_ttl_seconds: int = 30

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
