"""Executor HTTP service (port 8100). Agents call POST /v1/execute instead of calling tools directly."""
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from executor.config import get_settings
from executor.guardrail import GuardRail
from executor.service import Executor, refuse

ID = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$"


class ExecuteRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    action_id: str = Field(pattern=ID)
    tool: str = Field(pattern=ID)
    environment: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: float = Field(default=0, ge=0)
    reason: str | None = Field(default=None, max_length=2000)
    wait_seconds: float | None = Field(default=None, ge=0, le=600, description="How long to wait for an admin")


def create_app(guardrail_http: httpx.AsyncClient | None = None, redis: Redis | None = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if guardrail_http is None:
            app.state.http = httpx.AsyncClient(base_url=settings.guardrail_url, timeout=settings.guardrail_timeout_seconds)
        if redis is None:
            app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        yield
        if guardrail_http is None:
            await app.state.http.aclose()
        if redis is None:
            await app.state.redis.aclose()

    app = FastAPI(title="GuardRail Trusted Executor", version="1.0.0", lifespan=lifespan)
    if guardrail_http is not None:
        app.state.http = guardrail_http
    if redis is not None:
        app.state.redis = redis

    @app.get("/health")
    async def health(request: Request):
        return {"status": "ok"}

    @app.post("/v1/execute", summary="Run a tool only if GuardRail allows it")
    async def execute(data: ExecuteRequest, request: Request, x_api_key: str | None = Header(default=None)):
        if not x_api_key:
            r = refuse(401, "API_KEY_REQUIRED", "Send the agent's GuardRail key in X-API-Key.")
        else:
            ex = Executor(GuardRail(request.app.state.http), request.app.state.redis, settings)
            payload = data.model_dump(exclude={"wait_seconds"})
            r = await ex.execute(x_api_key, payload, data.wait_seconds)
        return JSONResponse(r.body, status_code=r.status, headers=r.headers)

    return app


app = create_app()
