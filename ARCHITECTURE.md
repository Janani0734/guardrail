# GuardRail architecture

## 1. System design
```
                         ┌──────────────────────────── Next.js (App Router) ───────────────────────────┐
 Admin browser ─────────▶│ pages (client components, TanStack Query)   /api/auth/*  (sets httpOnly cookies)│
                         │                                             /api/proxy/v1/*  (adds Bearer JWT)│
                         └──────────────────────────────────────┬──────────────────────────────────────┘
                                                                │ BACKEND_URL (server-side only)
 AI agent ──X-API-Key──▶ ┌──────────────────────────────────────▼──────────────────────────────────────┐
                         │ FastAPI   routers → services → repositories → SQLAlchemy 2 (async)           │
                         │           policy_engine (pure)   rate limiter / repeat tracker   audit chain │
                         │           expiry worker (asyncio task or `python -m app.workers.expiry`)     │
                         └───────────────┬─────────────────────────────────────┬────────────────────────┘
                                         ▼                                     ▼
                                  PostgreSQL (truth)                    Redis (ephemeral state)
```
Layering rules: routers contain only HTTP concerns (parse, auth dependency, status code); services hold business logic and own transactions (`commit()`); repositories hold queries and always take `org_id`; Pydantic schemas validate every input and shape every output (no ORM object, hash or secret is serialised implicitly).

## 2. Request lifecycle — `POST /v1/actions/evaluate`
1. **Authenticate**: HMAC the `X-API-Key`, look it up, reject revoked/expired keys with one generic 401, reject disabled agents (403).
2. **Bind**: body `agent_id` must equal the key's agent (stops a leaked key acting as someone else).
3. **Idempotency**: `(org, agent, action_id)` already stored → replay the stored decision (409 if the payload fingerprint differs). Transiently denied rows (rate limit / temp block) are re-evaluated instead.
4. **Redact**: arguments and reason are scrubbed *before* anything is persisted; the engine still sees the raw values in memory so policies can match them.
5. **Load context**: active policies, tool registration, agent↔tool permission.
6. **Redis stage** (fail closed → 503 on Redis errors): temp-block check for this fingerprint → sliding-window rate limit(s).
7. **Policy engine** (pure function): unknown/unpermitted tool → BLOCK; else evaluate rule policies, choose by precedence.
8. **Persist in one transaction**: `action_requests`, `policy_decisions` (with trace), `approvals` (if gated), `rate_limit_events` (if throttled), `api_keys.last_used_at` (≤ 1 write/min), and one hash-chained `audit_logs` row; `COMMIT`.
9. **After commit, best-effort Redis**: repeat counter for BLOCKs, `approval:{id}` state hash, analytics version bump. A failure here is logged, never fatal — PostgreSQL already holds the truth.
10. **Respond**: 200 ALLOW/BLOCK, 202 REQUIRE_APPROVAL, 429 rate limited.

## 3. Database schema (PostgreSQL)
All tables: UUID primary key, `created_at`, `updated_at` (timestamptz). Enums are `VARCHAR` + `CHECK` (non-native) so adding a value never needs `ALTER TYPE`.

| Table | Purpose / key constraints |
|---|---|
| `organizations` | tenant; unique `slug` |
| `users` | unique `email`, `password_hash` (bcrypt over SHA-256 pre-hash) |
| `memberships` | user↔org with `role` ADMIN/MANAGER/VIEWER; unique `(organization_id, user_id)` |
| `agents` | `slug` is the public `agent_id`; unique `(organization_id, slug)`; status ACTIVE/DISABLED |
| `api_keys` | `key_hash` (HMAC-SHA-256, unique), display `prefix`, `revoked_at`, `expires_at`, `last_used_at`; no plaintext |
| `tools` | unique `(organization_id, name)`, `risk_level`, `is_active` |
| `agent_tools` | allow-list; unique `(agent_id, tool_id)` |
| `policies` | `policy_type` RULE/RATE_LIMIT/UNKNOWN_TOOL/REPEATED_ACTION, `effect`, `priority`, `reason_code`, `message`, JSONB `config`; unique `(organization_id, name)`; index `(org, is_active, priority)` |
| `policy_rules` | `(field, operator, value JSONB, position)`, cascade-deleted with the policy |
| `action_requests` | one row per `(org, agent, action_id)` (unique); redacted `arguments`, `fingerprint`, `decision`, `status`, `outcome`; indexes on `agent_id`, `action_id`, `status`, `environment`, `tool`, `created_at`, `(org, created_at)` |
| `policy_decisions` | 1:1 with the action; `policy_id` (SET NULL if the policy is later deleted), `reason_code`, `message`, JSONB `trace` |
| `approvals` | 1:1 with the action; `status` PENDING/APPROVED/REJECTED/EXPIRED, `expires_at`, `decided_by`, `decided_at`, `decision_reason`; index `(status, expires_at)` for the sweeper |
| `audit_logs` | per-org `seq`, actor, event, entity, JSONB `details`, `prev_hash`, `entry_hash`; unique `(org, seq)`; FK `ON DELETE RESTRICT`; **trigger blocks UPDATE/DELETE/TRUNCATE** |
| `rate_limit_events` | persisted record of every throttle (scope, limit, window, observed) |

Foreign keys cascade from organizations except audit logs. Money-like values use `NUMERIC(14,4)`.

## 4. Redis usage (never the source of truth)
| Key | Type / TTL | Purpose |
|---|---|---|
| `rl:{scope}:{id}:{policy}` | ZSET, window+1 s | sliding-window rate limit (MULTI: trim, add, count) |
| `repeat:{org}:{agent}:{fp}` | counter, window | failed/blocked/rejected repeats of an identical action |
| `tempblock:{org}:{agent}:{fp}` | string, block duration | active temporary block; its TTL is the `Retry-After` |
| `approval:{id}` | hash, until expiry + token TTL | fast agent polling state; holds the one-time token until it is read |
| `approval_token:{sha256}` | string, 15 min | redeemable token → `approval_id|action_id|agent_id`; consumed with atomic `GETDEL` |
| `analytics:ver:{org}` / `analytics:{org}:v{n}:…` | counter / JSON, 30 s | dashboard cache; bumping the version orphans stale entries (O(1) invalidation, no `KEYS`) |
| `lock:approval-expiry` | string, 30 s | worker coordination (`SET NX EX`) |
| `revoked_jti:{jti}` | string, until token expiry | refresh-token revocation list |
| `login_attempts:{email}` | counter, 5 min | brute-force throttle |

Redis loss behaviour: evaluation **fails closed** (503). Approval state/tokens are re-derivable from PostgreSQL except the unread one-time token (the agent can ask an admin to re-approve). Analytics simply recompute.

## 5. Security model
- **Passwords**: bcrypt (cost 12) over a SHA-256 pre-hash (removes bcrypt's 72-byte truncation); identical error + dummy hash for unknown users (no account enumeration); 10 attempts / 5 min throttle.
- **Tokens**: HS256 JWT, 15-min access, 7-day refresh with rotation and Redis revocation; token *type* is checked so a refresh token can't be used as an access token. Role and membership are re-read from PostgreSQL on every request, so demotion/removal is immediate.
- **API keys**: 256-bit random, `HMAC-SHA-256(pepper, key)` stored (a DB leak alone can't be brute-forced offline or verified), shown once, prefix shown for identification, one generic 401 for unknown/revoked/expired.
- **Tenant isolation (IDOR)**: every repository method takes `org_id` and filters on it; foreign ids are indistinguishable from nonexistent ones (404). Tool assignment re-validates ids against the org. Covered by tests.
- **Secrets**: redacted at ingestion by key name and token pattern (AWS, GitHub, Stripe, Slack, JWT, private keys, bearer tokens, DB URLs, `password=…`); the action fingerprint is keyed-HMAC so low-entropy arguments can't be dictionary-attacked from the DB.
- **Integrity**: hash-chained audit log, ORM guard, PostgreSQL trigger; `verify` endpoint walks the chain.
- **Browser**: tokens live in httpOnly, SameSite=Lax cookies; the Next.js proxy forwards only `/v1/**`; security headers on both tiers; CORS only needed for non-dashboard callers.
- **Fail closed**: Redis outage → 503; unknown/unassigned tool → BLOCK even with no policies.
- **Input hygiene**: Pydantic validation everywhere, 64 KB cap on arguments, regex length cap and compile-check on policy creation.

## 6. Policy engine
Policies belong to an organization and have a `priority` (lower first). A `RULE` policy is a list of `(field, operator, value)` conditions that must **all** match, plus an `effect`.
- Fields: `tool`, `environment`, `estimated_cost`, `agent_id`, `reason`, `arguments_text` (canonical JSON of the arguments — so one regex such as `\bDROP\s+TABLE\b` can inspect any argument shape), `arguments.<dotted.path>`.
- Resolution: matching policies are grouped by effect; **BLOCK wins over REQUIRE_APPROVAL wins over ALLOW**; within an effect the lowest priority number wins; no match → default ALLOW (`NO_POLICY_MATCHED`) for a permitted tool.
- Non-rule types are stateful and evaluated before the engine: `REPEATED_ACTION` (temp-block lookup), `RATE_LIMIT` (sliding window; several allowed, scope per agent or per key). With no such policy configured, secure defaults from settings apply. `UNKNOWN_TOOL` only customises the message/code of the always-on unknown-tool block.
- Every decision stores a trace (each evaluated policy and whether it matched) → explainability in the UI and simulator.

## 7. Approval workflow
```
REQUIRE_APPROVAL ──▶ approvals.PENDING (expires_at = now + policy ttl / default 30 min)
   │ admin/manager approve|reject (SELECT … FOR UPDATE; must still be PENDING and not overdue)
   ├─▶ APPROVED  → action_requests.status=APPROVED, one-time token in Redis, audit APPROVAL_APPROVED
   ├─▶ REJECTED  → status=REJECTED, counts toward the repeated-action guard, audit APPROVAL_REJECTED
   └─ timeout ─▶ EXPIRED (worker sweep every 15 s, or lazily on touch), audit APPROVAL_EXPIRED by SYSTEM
```
The agent polls `GET /v1/actions/{id}/status`; once approved it receives a token exactly once and can prove the approval with `POST /v1/approvals/verify-token` (single use, bound to the agent). Races (two approvers, approver vs. worker) are resolved by the row lock: the second actor sees 409.

## 8. Audit chain
`entry_hash = SHA-256(canonical JSON of {seq, org, actor, event, entity, details, created_at, prev_hash})`, appended under a per-org row lock so `seq`/`prev_hash` are consistent. Tampering with or deleting any historical row breaks verification at that row. Cost: appends for one organization serialise (documented trade-off).

## Trusted Executor (enforcement point)
GuardRail only *decides*. A well-behaved agent could still skip the check, so the Executor (`backend/executor/`, port 8100) is the component that actually runs tools: the agent calls `POST /v1/execute` and never calls a tool, and never holds an approval token.

```
agent ──X-API-Key──▶ Executor ──evaluate──▶ GuardRail
                        │  ◀── ALLOW / BLOCK / REQUIRE_APPROVAL
                        ├─ ALLOW             → run fake tool
                        ├─ BLOCK             → refuse (403 / 429)
                        └─ REQUIRE_APPROVAL  → poll status until an admin decides
                                               approved → read one-time token → verify-token (bound) → run
```
Order of checks: validate tool arguments (422) → evaluate → exactly-once record → decision → (approval wait, token redemption) → claim `action_id` → run → report outcome.

**Token binding.** When an admin approves, GuardRail stores `approval|action|agent|fingerprint` under a hash of the token in Redis, where the fingerprint is the keyed HMAC of `tool|environment|canonical JSON arguments` captured at evaluation. `POST /v1/approvals/verify-token` accepts the optional `action_id/tool/environment/arguments`, recomputes the fingerprint and compares in constant time. Redemption is `GETDEL` (atomic), so a token works once; any presentation, even a mismatched one, burns it. TTL = `approval_token_ttl_seconds` (default 15 min). The bare `{token}` call keeps its old agent-bound behaviour for existing clients.

**Fail closed.** GuardRail unreachable, timing out or answering 5xx → 503 `GUARDRAIL_UNAVAILABLE`, nothing runs. Executor's own Redis down → 503. Unknown decision → 502.

**Exactly once.** `SET NX` claim on `executor:exec:{sha256(api_key)}:{action_id}` before running; the finished response is cached (24 h), so a retry returns `replayed: true` without running the tool again. A crashed run frees its claim after 2 minutes.

**Trust boundary (honest).** The Executor is only a hard guarantee if it is the sole holder of real tool credentials and network access. Here the tools are fakes, so this is a reference implementation of the pattern.
