"""Simulated AI agent. It never calls tools itself: every action goes through the Trusted Executor.

    python scripts/demo_agent.py                 # run all scenarios against http://localhost:8100
    python scripts/demo_agent.py --only 2        # one scenario
    EXECUTOR_URL=http://localhost:8100 python scripts/demo_agent.py

Needs the full stack (docker compose --profile full up -d) and the seeded demo data. Standard library only.
Scenario 2 pauses until you approve it in the dashboard (http://localhost:3000 -> Approvals)."""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

EXECUTOR = os.environ.get("EXECUTOR_URL", "http://localhost:8100")
AGENT = "support-agent-01"
KEY = os.environ.get("AGENT_API_KEY", "grk_demo_support_agent_01_local_only_0001")  # seeded local demo key only

SCENARIOS = [
    ("1. Harmless read (expect ALLOW -> runs)", "read_logs", "staging", {"service": "api", "lines": 3}, 0),
    ("2. Email to every customer (expect REQUIRE_APPROVAL -> waits for you)", "send_email", "production",
     {"to": "all-customers@example.com", "subject": "Big news", "body": "Hello"}, 15),
    ("3. Delete records in production (expect BLOCK or approval, per your policies)", "delete_database_records",
     "production", {"table": "old_logs", "limit": 1000}, 12.5),
]


def post(body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(f"{EXECUTOR}/v1/execute", data=json.dumps(body).encode(), method="POST",
                                 headers={"X-API-Key": KEY, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except urllib.error.URLError as e:
        return 0, {"error": {"code": "EXECUTOR_UNREACHABLE", "message": str(e.reason)}}


def run(title: str, tool: str, env: str, args: dict, cost: float = 0) -> None:
    print(f"\n== {title}")
    body = {"agent_id": AGENT, "action_id": f"demo_{uuid.uuid4().hex[:8]}", "tool": tool, "environment": env,
            "arguments": args, "estimated_cost": cost, "reason": "demo agent", "wait_seconds": 10}
    while True:
        status, out = post(body)  # same action_id each time: the executor continues rather than starting over
        if status == 202:
            print("   waiting for an admin to approve... (open the dashboard -> Approvals)")
            time.sleep(1)
            continue
        break
    if out.get("executed"):
        print(f"   EXECUTED  {tool}: {json.dumps(out['result'])}")
    else:
        err = out.get("error", {})
        print(f"   NOT EXECUTED  HTTP {status}  {err.get('code') or out.get('reason_code')}  "
              f"{err.get('message') or out.get('message') or ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="run just scenario N")
    n = ap.parse_args().only
    for i, sc in enumerate(SCENARIOS, 1):
        if n is None or n == i:
            run(*sc)
    return 0


if __name__ == "__main__":
    sys.exit(main())