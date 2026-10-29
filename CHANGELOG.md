# Changelog

## 1.1.0 — Trusted Executor
- New `executor/` service (port 8100, compose `full` profile): enforces ALLOW / BLOCK / REQUIRE_APPROVAL before a tool runs; fails closed when GuardRail is unreachable
- Three fake tools: `read_logs`, `send_email`, `delete_database_records` (no real side effects)
- Approval tokens are now bound to agent + action + tool + environment + arguments (`verify-token` accepts the optional fields; old `{token}` calls unchanged); one-time and expiring
- Exactly-once execution per `action_id`
- `backend/scripts/demo_agent.py`; 15 new tests (111 total); `httpx` moved to runtime requirements

## 1.0.0 — Initial release

### Gateway & policy engine
- `POST /v1/actions/evaluate` returns ALLOW / BLOCK / REQUIRE_APPROVAL (202) / rate-limited BLOCK (429)
- Pure, I/O-free policy engine: AND-ed rules, 12 operators, nested `arguments.*` access, regex on serialised arguments
- Precedence BLOCK > REQUIRE_APPROVAL > ALLOW, lowest priority number first, full evaluation trace stored per decision
- Policy types: rule-based, rate limit, unknown tool, repeated-action guard
- Secure defaults: unregistered/unassigned tools blocked; default rate limit applies even with no policy
- Idempotent `action_id` (replay returns stored decision; payload mismatch → 409; concurrent duplicates collapse to one row)
- Fail-closed (503) when Redis is unavailable
- Policy simulation endpoint (no side effects)
- Secret detection and redaction before persistence (key-name based + token-format patterns)

### Approvals
- Pending queue, approve/reject with reason, row-locked transitions, one-time approval tokens (atomic GETDEL)
- Expiry worker with Redis lock + `FOR UPDATE SKIP LOCKED`; lazy expiry on touch
- Agent-facing status polling and outcome reporting (failed outcomes feed the repeat guard)

### Platform
- Orgs, users, memberships, ADMIN / MANAGER / VIEWER RBAC (role re-read from DB on every request)
- JWT access + rotating refresh tokens with Redis revocation, login throttling, bcrypt (SHA-256 pre-hash)
- Agents, tools, agent-tool permissions, API keys (HMAC-SHA-256 hashed, shown once, revocable, expirable)
- Hash-chained immutable audit log (ORM guard + PostgreSQL trigger + `verify` endpoint)
- Analytics with Redis cache and O(1) version-based invalidation
- IDOR-safe org scoping on every query (cross-tenant access returns 404)

### Dashboard (Next.js App Router)
- httpOnly-cookie sessions through a same-origin proxy (JWT never exposed to browser JS)
- Overview, agents, agent detail, API keys, tools, policies (templates + simulator), approvals, action history, audit logs (+ integrity check), analytics, settings/members
- Loading, empty, error and success states; role-aware controls; Zod-validated forms and API responses

### Tooling
- Alembic initial migration (PostgreSQL, includes audit immutability triggers); no schema drift (`alembic check`)
- Seed script (org, 3 users, 3 agents, 8 tools, 9 policies, ~150 actions, approvals in every state, audit trail)
- 96 pytest tests; run on SQLite + fakeredis by default or on PostgreSQL via `TEST_DATABASE_URL`
- Docker Compose for PostgreSQL + Redis, optional `full` profile for API + dashboard
