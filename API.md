# GuardRail API reference

Base URL `http://localhost:8000` · Interactive docs at `/docs` · All bodies are JSON.

## Authentication
| Caller | Mechanism |
|---|---|
| Dashboard users | `Authorization: Bearer <access JWT>` (15 min). Refresh tokens (7 d) are single-use and rotate. The Next.js app keeps both in httpOnly cookies and proxies calls, so browser JS never sees them. |
| AI agents | `X-API-Key: grk_…` — bound to exactly one agent. The body's `agent_id` must match that agent or the call is rejected (403 `AGENT_MISMATCH`). |

Roles: `VIEWER` (read) < `MANAGER` (agents, tools, keys, approvals) < `ADMIN` (policies, members, org, audit verification). The role is read from the database on every request.

## Error format
```json
{ "error": { "code": "INSUFFICIENT_ROLE", "message": "Requires role MANAGER or higher", "details": null } }
```
| Status | Meaning (examples of `code`) |
|---|---|
| 401 | `MISSING_TOKEN`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `TOKEN_REVOKED`, `INVALID_CREDENTIALS`, `MISSING_API_KEY`, `INVALID_API_KEY` |
| 403 | `INSUFFICIENT_ROLE`, `AGENT_MISMATCH`, `AGENT_DISABLED`, `LAST_ADMIN`, `NOT_A_MEMBER` |
| 404 | `*_NOT_FOUND` (also returned for other organizations' objects — no existence oracle) |
| 409 | `EMAIL_TAKEN`, `AGENT_SLUG_TAKEN`, `TOOL_NAME_TAKEN`, `POLICY_NAME_TAKEN`, `ACTION_ID_REUSED`, `APPROVAL_NOT_PENDING`, `APPROVAL_EXPIRED`, `OUTCOME_NOT_ALLOWED`, `OUTCOME_ALREADY_REPORTED`, `ALREADY_MEMBER` |
| 422 | `VALIDATION_ERROR` (with `details[]`), `INVALID_RULE_FIELD`, `INVALID_RULE_VALUE`, `INVALID_POLICY_CONFIG`, `UNKNOWN_TOOL_IDS` |
| 429 | `LOGIN_THROTTLED`; evaluate rate limit (decision body, see below). Always has `Retry-After` |
| 503 | `STATE_STORE_UNAVAILABLE` (Redis down; the action is **not** authorised) |

Paginated lists return `{ "items": [], "total": 0, "page": 1, "page_size": 20, "pages": 1 }` and accept `page`, `page_size` (max 100).

---
## Agent-facing endpoints (`X-API-Key`)

### `POST /v1/actions/evaluate`
Request:
```json
{ "agent_id": "support-agent-01", "action_id": "act_123", "tool": "delete_database_records",
  "environment": "production", "arguments": {"table": "old_logs", "limit": 1000},
  "estimated_cost": 12.5, "reason": "Clean expired log records" }
```
`action_id` is the idempotency key (per agent). Repeating it with the same payload returns the stored decision (`X-Idempotent-Replay: true`); with a different payload → 409.

| HTTP | Body |
|---|---|
| 200 ALLOW | `{"decision":"ALLOW","action_id":"act_123","policy_id":null,"expires_at":null}` |
| 200 BLOCK | `{"decision":"BLOCK","action_id":"act_123","reason_code":"FORBIDDEN_TOOL_IN_PRODUCTION","message":"Tool delete_database_records is blocked in production","policy_id":"<uuid>"}` |
| 202 REQUIRE_APPROVAL | `{"decision":"REQUIRE_APPROVAL","action_id":"act_123","approval_id":"<uuid>","expires_at":"2026-10-27T12:00:00.000000Z","message":"High-cost action requires admin approval","policy_id":"<uuid>"}` |
| 429 | BLOCK body with `reason_code":"RATE_LIMIT_EXCEEDED"` + `Retry-After` |

Built-in reason codes: `UNKNOWN_TOOL`, `TOOL_NOT_PERMITTED`, `RATE_LIMIT_EXCEEDED`, `REPEATED_ACTION_BLOCKED`, `NO_POLICY_MATCHED` (ALLOW); policy-defined codes otherwise. A rate-limited or temp-blocked `action_id` can be retried later and is re-evaluated.

### `GET /v1/actions/{action_id}/status`
```json
{ "action_id":"act_124","decision":"REQUIRE_APPROVAL","status":"APPROVED","approval_id":"<uuid>",
  "approval_status":"APPROVED","expires_at":"…","decision_reason":"Looks fine","approval_token":"apt_…" }
```
`status` ∈ ALLOWED, BLOCKED, PENDING_APPROVAL, APPROVED, REJECTED, EXPIRED. `approval_token` is returned **once**, only after approval.

### `POST /v1/approvals/verify-token`
`{"token":"apt_…"}` → `{"valid":true,"action_id":"act_124","approval_id":"<uuid>"}`. Single use, bound to the issuing agent, expires after 15 min (configurable).

### `POST /v1/actions/{action_id}/outcome`
`{"outcome":"SUCCEEDED"|"FAILED","detail":"optional"}` → `{"action_id":…,"outcome":…,"temporarily_blocked":false}`. Only for ALLOWED/APPROVED actions, once. `FAILED` outcomes count toward the repeated-action guard.

---
## Dashboard endpoints (`Bearer`)

### Auth
| Method & path | Role | Notes |
|---|---|---|
| `POST /v1/auth/register` | public | `{email, password(≥10), full_name, organization_name}` → 201 `{tokens, user, organization, role:"ADMIN"}` |
| `POST /v1/auth/login` | public | `{email, password, organization_id?}`; throttled per email |
| `POST /v1/auth/refresh` | public | `{refresh_token}` → new pair; old refresh token is revoked |
| `POST /v1/auth/logout` | public | `{refresh_token}` revokes it |
| `GET /v1/auth/me` | any | current user, organization, role |

### Agents, keys, tools
| Method & path | Role | Notes |
|---|---|---|
| `GET /v1/agents` | VIEWER | `search`, `status` |
| `POST /v1/agents` | MANAGER | `{slug, name, description?}` → 201 |
| `GET/PATCH /v1/agents/{id}` | VIEWER / MANAGER | PATCH `{name?, description?, status?: ACTIVE\|DISABLED}` |
| `GET/PUT /v1/agents/{id}/tools` | VIEWER / MANAGER | PUT `{tool_ids: []}` replaces the allow-list |
| `POST /v1/agents/{id}/api-keys` | MANAGER | `{name, expires_in_days?}` → 201 incl. `key` (**only time it is shown**) |
| `GET /v1/api-keys` | VIEWER | `agent_id`, `active_only`; never returns hashes |
| `DELETE /v1/api-keys/{id}` | MANAGER | revokes (idempotent) |
| `GET/POST /v1/tools`, `PATCH /v1/tools/{id}` | VIEWER / MANAGER | `{name, description?, risk_level}`; PATCH `{is_active?, risk_level?, description?}` |

### Policies
| Method & path | Role |
|---|---|
| `GET /v1/policies` (`policy_type`, `effect`, `is_active`, `search`) | VIEWER |
| `POST /v1/policies`, `PATCH /v1/policies/{id}`, `DELETE /v1/policies/{id}` | ADMIN |
| `POST /v1/policies/simulate` | VIEWER |

Create example (rule-based):
```json
{ "name": "Block delete in prod", "policy_type": "RULE", "effect": "BLOCK", "priority": 20,
  "reason_code": "FORBIDDEN_TOOL_IN_PRODUCTION", "message": "Tool delete_database_records is blocked in production",
  "rules": [ {"field":"tool","operator":"eq","value":"delete_database_records"},
             {"field":"environment","operator":"eq","value":"production"} ] }
```
- Rule `field`: `tool`, `environment`, `estimated_cost`, `agent_id`, `reason`, `arguments_text` (arguments serialised to JSON), `arguments.<path>`.
- `operator`: `eq neq in not_in gt gte lt lte contains not_contains startswith regex` (string matching is case-insensitive; regex ≤ 300 chars).
- All rules of a policy must match. Other types: `RATE_LIMIT` `{limit, window_seconds, scope: agent|api_key}`, `REPEATED_ACTION` `{threshold, window_seconds, block_seconds}`, `UNKNOWN_TOOL` (no config). `REQUIRE_APPROVAL` rule policies accept `config.ttl_minutes`.

Simulate: `{agent_id, tool, environment, arguments, estimated_cost, reason?}` → `{decision, reason_code, message, policy_id, policy_name, tool_known, tool_permitted, trace[], note}`. No rows are written and Redis counters are untouched.

### Actions, approvals, audit, analytics
| Method & path | Role | Notes |
|---|---|---|
| `GET /v1/action-history` | VIEWER | filters `agent_id, tool, environment, decision, status, search, date_from, date_to`; `sort_by` (created_at, estimated_cost, tool, environment), `order` |
| `GET /v1/action-history/{id}` | VIEWER | adds evaluation `trace` and `latency_ms` |
| `GET /v1/approvals` | VIEWER | `status`, `agent_id`, `environment` (PENDING list hides overdue rows) |
| `GET /v1/approvals/{id}` | VIEWER | |
| `POST /v1/approvals/{id}/approve` / `/reject` | MANAGER | `{reason?}`; 409 if not pending / expired |
| `GET /v1/audit-logs` | VIEWER | `event_type, entity_type, entity_id, actor_type, date_from, date_to, order` |
| `GET /v1/audit-logs/verify` | ADMIN | `{valid, checked, first_invalid_seq}` |
| `GET /v1/analytics?days=7` | VIEWER | totals, approval counts, time series, per-agent activity, top tools, block reasons (Redis-cached ~30 s, invalidated on activity) |

### Organization & members
`GET /v1/organization` (VIEWER) · `PATCH /v1/organization` `{name}` (ADMIN) · `GET /v1/members` (VIEWER) · `POST /v1/members` `{email, full_name, password, role}` (ADMIN) · `PATCH /v1/members/{user_id}` `{role}` (ADMIN) · `DELETE /v1/members/{user_id}` (ADMIN). The last admin cannot be demoted or removed.

### System
`GET /health` → `{"status":"ok","database":"ok","redis":"ok"}` (503 when degraded).
