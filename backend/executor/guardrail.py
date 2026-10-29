"""Thin GuardRail client used by the Executor. Any failure to get a trustworthy answer raises GuardRailUnavailable,
which the Executor turns into a refusal: if GuardRail is down, nothing runs."""
from typing import Any

import httpx


class GuardRailUnavailable(Exception):
    pass


class GuardRail:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def _send(self, method: str, path: str, api_key: str, **kw) -> httpx.Response:
        try:
            r = await self.http.request(method, path, headers={"X-API-Key": api_key}, **kw)
        except httpx.HTTPError as exc:
            raise GuardRailUnavailable(type(exc).__name__) from exc
        if r.status_code >= 500:
            raise GuardRailUnavailable(f"HTTP {r.status_code}")
        return r

    @staticmethod
    def _json(r: httpx.Response) -> dict[str, Any]:
        try:
            body = r.json()
        except ValueError as exc:
            raise GuardRailUnavailable("non-JSON response") from exc
        if not isinstance(body, dict):
            raise GuardRailUnavailable("unexpected response")
        return body

    async def evaluate(self, api_key: str, payload: dict) -> tuple[int, dict, httpx.Headers]:
        r = await self._send("POST", "/v1/actions/evaluate", api_key, json=payload)
        return r.status_code, self._json(r), r.headers

    async def status(self, api_key: str, action_id: str) -> tuple[int, dict]:
        r = await self._send("GET", f"/v1/actions/{action_id}/status", api_key)
        return r.status_code, self._json(r)

    async def verify_token(self, api_key: str, payload: dict) -> tuple[int, dict]:
        r = await self._send("POST", "/v1/approvals/verify-token", api_key, json=payload)
        return r.status_code, self._json(r)

    async def report_outcome(self, api_key: str, action_id: str, outcome: str) -> None:
        try:  # best effort: the action already ran, a lost report must not turn into an error
            await self.http.post(f"/v1/actions/{action_id}/outcome", headers={"X-API-Key": api_key},
                                 json={"outcome": outcome})
        except httpx.HTTPError:
            pass
