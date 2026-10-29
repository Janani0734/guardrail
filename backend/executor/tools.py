"""Fake tools. They never touch email, databases or the network - they only return sample responses.

Arguments are validated before GuardRail is ever asked, so a malformed call is rejected cheaply. Results never echo
free-form argument values that could hold secrets (e.g. an email body)."""
import re
import uuid
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadLogsArgs(_Args):
    service: str = Field(default="api", max_length=64)
    lines: int = Field(default=3, ge=1, le=100)


class SendEmailArgs(_Args):
    to: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    subject: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=5000)


class DeleteRecordsArgs(_Args):
    table: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    limit: int = Field(default=1, ge=1, le=1_000_000)


async def read_logs(a: ReadLogsArgs) -> dict[str, Any]:
    sample = ["INFO service started", "INFO health check ok", "WARN slow request (sample)"]
    return {"simulated": True, "service": a.service, "lines": sample[: a.lines]}


async def send_email(a: SendEmailArgs) -> dict[str, Any]:
    return {"simulated": True, "message_id": f"msg_fake_{uuid.uuid4().hex[:8]}", "to": a.to,
            "note": "No email was sent. This is a fake tool."}


async def delete_database_records(a: DeleteRecordsArgs) -> dict[str, Any]:
    return {"simulated": True, "table": a.table, "records_deleted": 0, "requested_limit": a.limit,
            "note": "Nothing was deleted. This is a fake tool."}


TOOLS: dict[str, tuple[type[BaseModel], Callable[[Any], Awaitable[dict[str, Any]]]]] = {
    "read_logs": (ReadLogsArgs, read_logs),
    "send_email": (SendEmailArgs, send_email),
    "delete_database_records": (DeleteRecordsArgs, delete_database_records),
}
_ = re  # (kept for clarity: patterns above are plain regex strings)
