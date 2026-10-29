"""Trusted Executor: enforces GuardRail's decision before a tool runs.

    agent -> Executor -> GuardRail (decide) -> Executor runs or refuses the tool

The agent never calls tools directly and never holds a token: the Executor asks GuardRail, waits for an admin when
needed, redeems the one-time approval token itself (bound to agent + action + tool + arguments) and only then runs
the tool, at most once per action_id."""
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from executor.config import ExecutorSettings
from executor.guardrail import GuardRail, GuardRailUnavailable
from executor.tools import TOOLS


@dataclass
class Result:
    status: int
    body: dict
    headers: dict = field(default_factory=dict)


def refuse(status: int, code: str, message: str, **extra) -> Result:
    return Result(status, {"executed": False, "error": {"code": code, "message": message}, **extra})


class Executor:
    def __init__(self, guardrail: GuardRail, redis: Redis, settings: ExecutorSettings):
        self.gr, self.redis, self.s = guardrail, redis, settings

    @staticmethod
    def _record_key(api_key: str, action_id: str) -> str:
        return f"executor:exec:{hashlib.sha256(api_key.encode()).hexdigest()[:32]}:{action_id}"

    async def execute(self, api_key: str, req: dict, wait_seconds: float | None) -> Result:
        try:
            return await self._execute(api_key, req, wait_seconds)
        except GuardRailUnavailable:
            return refuse(503, "GUARDRAIL_UNAVAILABLE", "GuardRail could not be reached; the action was NOT executed.")
        except RedisError:
            return refuse(503, "EXECUTOR_STATE_UNAVAILABLE", "Executor state store unavailable; action NOT executed.")

    async def _execute(self, api_key: str, req: dict, wait_seconds: float | None) -> Result:
        tool = TOOLS.get(req["tool"])
        if tool is None:
            return refuse(501, "TOOL_NOT_IMPLEMENTED", f"The executor has no implementation for '{req['tool']}'.")
        args_model, fn = tool
        try:
            parsed = args_model.model_validate(req["arguments"])
        except ValidationError as exc:
            fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
            return refuse(422, "TOOL_ARGUMENTS_INVALID", "Tool arguments are invalid.", fields=fields)

        status, body, headers = await self.gr.evaluate(api_key, req)
        decision = body.get("decision")
        if decision is None:  # 401/403/404/409/422 from GuardRail itself: pass the reason through, run nothing
            return refuse(status, "GUARDRAIL_REJECTED_REQUEST", "GuardRail rejected the request.",
                          guardrail_error=body.get("error", body))
        action_id = req["action_id"]
        key = self._record_key(api_key, action_id)

        if decision == "BLOCK":
            extra = {"retry_after": headers["retry-after"]} if "retry-after" in headers else {}
            return Result(429 if status == 429 else 403, {
                "executed": False, "decision": "BLOCK", "action_id": action_id,
                "reason_code": body.get("reason_code"), "message": body.get("message")},
                {"Retry-After": headers["retry-after"]} if extra else {})
        if decision not in ("ALLOW", "REQUIRE_APPROVAL"):
            return refuse(502, "UNKNOWN_DECISION", "GuardRail returned an unknown decision; action NOT executed.")

        cached = await self.redis.get(key)
        if cached:
            data = json.loads(cached)
            if data["state"] == "DONE":
                return Result(200, {**data["response"], "replayed": True})
            return refuse(409, "EXECUTION_IN_PROGRESS", "This action_id is already being executed.")

        if decision == "REQUIRE_APPROVAL":
            gate = await self._await_approval(api_key, req, body, wait_seconds)
            if isinstance(gate, Result):
                return gate

        # Exactly-once: only one caller can claim this action_id.
        if not await self.redis.set(key, json.dumps({"state": "RUNNING"}), nx=True, ex=self.s.running_ttl_seconds):
            return refuse(409, "EXECUTION_IN_PROGRESS", "This action_id is already being executed.")
        try:
            output = await fn(parsed)
        except Exception:  # noqa: BLE001 - never leak tool internals; a failed run can be retried only if still authorised
            await self.redis.delete(key)
            await self.gr.report_outcome(api_key, action_id, "FAILED")
            return refuse(500, "TOOL_FAILED", "The tool failed.")
        response = {"executed": True, "decision": decision, "action_id": action_id, "tool": req["tool"],
                    "approved_by_human": decision == "REQUIRE_APPROVAL", "result": output}
        await self.redis.set(key, json.dumps({"state": "DONE", "response": response}), ex=self.s.record_ttl_seconds)
        await self.gr.report_outcome(api_key, action_id, "SUCCEEDED")
        return Result(200, response)

    async def _await_approval(self, api_key: str, req: dict, eval_body: dict, wait_seconds: float | None):
        """Returns None when the action may run now, otherwise a Result explaining why it may not."""
        action_id = req["action_id"]
        wait = min(max(self.s.default_wait_seconds if wait_seconds is None else wait_seconds, 0), self.s.max_wait_seconds)
        deadline = time.monotonic() + wait
        while True:
            _, st = await self.gr.status(api_key, action_id)
            approval = st.get("approval_status")
            if approval != "PENDING":
                break
            if time.monotonic() >= deadline:
                return Result(202, {"executed": False, "decision": "REQUIRE_APPROVAL", "status": "PENDING_APPROVAL",
                                    "action_id": action_id, "approval_id": eval_body.get("approval_id"),
                                    "message": "Waiting for admin approval. Send the same request again to continue."})
            await asyncio.sleep(min(self.s.poll_interval_seconds, max(deadline - time.monotonic(), 0.01)))

        if approval == "REJECTED":
            return refuse(403, "APPROVAL_REJECTED", "An admin rejected this action.", action_id=action_id,
                          decision_reason=st.get("decision_reason"))
        if approval == "EXPIRED":
            return refuse(403, "APPROVAL_EXPIRED", "The approval request expired before an admin decided.",
                          action_id=action_id)
        token = st.get("approval_token")
        if not token:  # shown to a caller only once; a retry after a lost response needs a fresh approval
            return refuse(409, "APPROVAL_TOKEN_UNAVAILABLE",
                          "Approved, but the one-time token was already issued. Request a new approval.",
                          action_id=action_id)
        vstatus, v = await self.gr.verify_token(api_key, {
            "token": token, "action_id": action_id, "tool": req["tool"],
            "environment": req["environment"], "arguments": req["arguments"]})
        if vstatus != 200 or not v.get("valid"):
            return refuse(403, "APPROVAL_TOKEN_INVALID", "The approval token was refused; action NOT executed.",
                          action_id=action_id, reason=v.get("reason"))
        return None
