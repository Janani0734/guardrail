# GuardRail — interview guide

Be precise about what is built and verified. Everything below describes the code in this repository.

## 30-second pitch
“GuardRail is a gateway that sits between an AI agent and the actions it wants to take. Each request is checked against org-defined policies and gets ALLOW, BLOCK or REQUIRE_APPROVAL. Approvals go to a Next.js dashboard where an admin approves or rejects; unanswered ones expire. It's built on FastAPI, PostgreSQL and Redis, with RBAC, hashed API keys, secret redaction and a hash-chained audit log.”

## 60-second pitch
“AI agents can call tools that delete data or spend money, and prompts alone don't make that safe. GuardRail enforces policy at runtime. An agent authenticates with an API key and calls `POST /v1/actions/evaluate`. I redact secrets, check idempotency, apply a Redis sliding-window rate limit and a repeated-failure guard, then run a pure policy engine: BLOCK beats REQUIRE_APPROVAL beats ALLOW, lowest priority first, and every decision stores a trace. Anything gated waits in an approval queue; a worker expires it if nobody answers, and approving mints a one-time token. PostgreSQL is the source of truth; Redis only holds ephemeral state, and if Redis is down the gateway fails closed. All of it is multi-tenant and role-based, and every decision goes into a tamper-evident audit log. I tested it with 96 tests, run on both SQLite and real PostgreSQL.”

## 3-minute technical explanation
1. **Problem**: autonomous agents need a control point that is deterministic, auditable and human-overridable.
2. **Hot path**: authenticate (HMAC-hashed key) → bind to agent → idempotency on `(org, agent, action_id)` → redact → Redis stage (temp block, rate limit) → policy engine → single DB transaction (action, decision+trace, approval, audit) → best-effort Redis side effects.
3. **Policy engine**: policies are data (field/operator/value rows ANDed together) so admins can change them without deploys; the engine is a pure function, so it is unit-tested without I/O and reused for simulation.
4. **Consistency**: DB is authoritative. Redis writes happen after commit and failure is non-fatal, except in the evaluation stage where Redis is a *safety* control, so we fail closed.
5. **Approvals**: a state machine guarded by `SELECT … FOR UPDATE`; a sweeper with `SKIP LOCKED` and a Redis lock expires overdue rows; tokens are redeemed via atomic `GETDEL`.
6. **Trust**: hashed keys, tenant-scoped queries (cross-tenant → 404), role re-read per request, hash-chained audit log plus a DB trigger.
7. **Frontend**: Next.js App Router; tokens are httpOnly cookies and a same-origin proxy attaches the JWT, so XSS can't steal it.

## Architecture, database, Redis, security — short answers
- **Architecture**: routers → services → repositories → async SQLAlchemy; services own transactions; pure engine in the middle. See ARCHITECTURE.md.
- **Database**: 14 normalized tables, UUID PKs, org-scoped uniqueness, CHECK-constrained enum columns, JSONB for policy config/trace, indexes on the filters the UI uses, FK `RESTRICT` on audit logs.
- **Redis**: sliding-window ZSETs, repeat counters + temp-block keys, approval state hash and one-time tokens, analytics cache with version keys, worker lock, refresh-token revocation, login throttle. Never the source of truth.
- **Security**: bcrypt+pre-hash, rotating refresh tokens, HMAC API keys, IDOR tests, redaction before persistence, fail-closed, audit chain.

## 30 likely questions
**1. Why a gateway instead of prompt-level guardrails?** Prompts are advisory; the model can be jailbroken or just wrong. A gateway enforces rules outside the model, deterministically, and produces an audit trail. It complements prompt safety rather than replacing it.

**2. Why is the policy engine a pure function?** No DB/Redis inside means fast unit tests, exact reuse for the simulate endpoint and the seed script, and no hidden state in decisions. State-dependent checks (rate limit, temp block) are resolved before it and passed as outcomes.

**3. How do you resolve conflicting policies?** Group matches by effect: BLOCK > REQUIRE_APPROVAL > ALLOW; within an effect the lowest `priority` number wins. Deny-overrides is the safe default because adding an allow rule can never silently weaken a block.

**4. What happens if no policy matches?** If the tool is registered and assigned to the agent: ALLOW with reason `NO_POLICY_MATCHED`. Unknown or unassigned tools are blocked regardless of policies. I'd flip to default-deny per org as a future setting.

**5. How are API keys stored and validated?** 256-bit random key, shown once; only `HMAC-SHA-256(pepper, key)` is stored with a short display prefix. Validation hashes the presented key and does a unique-index lookup. Because the key has 256 bits of entropy a fast keyed hash is appropriate (no need for bcrypt), and the pepper means a DB-only leak can't verify guesses.

**6. Why bcrypt for passwords but HMAC for API keys?** Passwords are low-entropy and need a slow hash. API keys are high-entropy random strings, and the lookup happens on every agent request, so a slow hash would only add latency without security benefit.

**7. Why pre-hash passwords with SHA-256?** bcrypt silently truncates at 72 bytes; pre-hashing makes long passphrases fully significant and avoids the NUL-byte pitfall.

**8. How does rate limiting work and why a sliding window?** A ZSET per scope: in one MULTI I trim old entries, add the current one, count, and set TTL. Unlike fixed windows it has no burst-at-the-boundary problem. Trade-off: memory proportional to the limit, and rejected attempts also count (deliberate penalty for hammering).

**9. Is the rate limit race-free?** The trim+add+count runs inside MULTI/EXEC, so concurrent requests are serialised by Redis. Under a Redis Cluster the key must live on one slot, which it does since it's a single key.

**10. What if Redis goes down?** Evaluation fails closed with 503 `STATE_STORE_UNAVAILABLE` — the gateway can't enforce rate limits or temp blocks, so it won't authorise. Non-critical Redis writes after commit (state hash, cache) just log. This is tested.

**11. Why is PostgreSQL the source of truth and Redis not?** Redis can lose data (eviction, restart, failover). Decisions, approvals and audits must survive, so they commit in PostgreSQL first; Redis holds derived or time-boxed state.

**12. How do you make evaluate idempotent?** Unique `(organization_id, agent_id, action_id)`. A repeat with the same payload fingerprint replays the stored decision; a different payload is 409. Concurrent duplicates hit the unique constraint, the loser catches `IntegrityError`, rolls back and returns the winner's row (tested with 5 parallel calls).

**13. Why store a fingerprint and why HMAC it?** It lets me detect payload mismatch and group identical actions for the repeat guard without storing raw arguments. Plain SHA-256 of low-entropy arguments could be brute-forced if the DB leaked, so it's keyed.

**14. How do you prevent secrets from leaking into the DB or logs?** Redaction happens in the service before persistence, using key-name rules and token patterns. The engine still evaluates the raw values in memory, and traces contain only policy names/ids. Limitation: regexes can't catch an arbitrary unlabelled secret.

**15. How does the approval flow avoid races?** The approval row is locked `FOR UPDATE`; the transition requires `PENDING` and `expires_at > now`. A second approver, or the expiry worker, sees a non-pending status and gets 409.

**16. How does expiry work with multiple workers?** The sweeper claims rows with `FOR UPDATE SKIP LOCKED`, and a Redis `SET NX EX` lock avoids duplicated effort. It's idempotent, so overlapping runs are harmless. Overdue rows are also expired lazily when touched, so correctness doesn't depend on the worker's timing.

**17. What's the approval token for?** After approval the agent gets a one-time token it can redeem via `verify-token`; `GETDEL` makes check-and-consume atomic, it's bound to the issuing agent, and it expires. It lets the executing component prove a human approved *this* action.

**18. How is the audit log immutable?** Three layers: no update/delete code paths, an ORM listener that raises on update/delete, and a PostgreSQL trigger that rejects UPDATE/DELETE/TRUNCATE (I verified it with raw SQL). Plus a hash chain so even a privileged edit is detectable.

**19. What does the hash chain actually guarantee?** Detectability, not prevention: modification or deletion in the middle breaks `entry_hash`/`prev_hash` at that point. An attacker with write access who recomputes the whole tail could forge it, so for stronger guarantees you'd anchor the latest hash externally (e.g., periodic signed checkpoints) — a documented future improvement.

**20. How do you prevent IDOR?** Every repository query includes `organization_id`; ids from other orgs return 404, the same as nonexistent ids. Role/org come from the verified token plus a membership lookup, never from request parameters. There are tests where a second org attempts read/modify/delete across agents, keys, tools, approvals and history.

**21. How does RBAC work?** Three ordered roles and dependency-injected guards (`Viewer`, `Manager`, `Admin`). The role is read from the DB per request so demotion is immediate; the UI hides controls but the API is the enforcement point. Guards also prevent removing the last admin.

**22. How do refresh tokens work?** Short access tokens, 7-day refresh tokens with a `jti`. Refresh rotates: the old `jti` goes to a Redis revocation set until its natural expiry; reuse returns `TOKEN_REVOKED`. Logout revokes too.

**23. Why httpOnly cookies and a proxy instead of localStorage?** XSS can read localStorage tokens. With httpOnly cookies and a same-origin proxy, JS never sees the JWT. Trade-off: CSRF becomes relevant — SameSite=Lax plus JSON-only mutating endpoints mitigate it; a CSRF token would harden it further.

**24. Why async SQLAlchemy and what are the pitfalls?** The service is I/O-bound (DB + Redis), so async keeps workers busy. Pitfalls I hit: attributes expire after rollback and lazy loading raises `MissingGreenlet` — I capture plain ids before the transactional section and use eager loading (`selectin`/`joined`) for relationships.

**25. How do you test it?** 96 tests: policy engine unit tests, API tests through httpx's ASGI transport, fakeredis for Redis, SQLite by default for speed and real PostgreSQL via `TEST_DATABASE_URL` (the same suite passes on both). I also tested time-dependent behaviour by aging rows rather than sleeping.

**26. Why SQLite in tests if production is PostgreSQL?** Hermetic, instant CI with zero services. Portability is preserved with `Uuid`, JSON-with-JSONB-variant and non-native enums; row locks are no-ops on SQLite, which is why I also run the suite on PostgreSQL where concurrency (unique-constraint race, `FOR UPDATE`) is real.

**27. How would this scale?** API is stateless → horizontal scaling. Redis handles hot counters. Bottlenecks: the per-org audit append lock (serialises writes per tenant) and analytics queries. Mitigations: batch audit appends per request, partition `action_requests`/`audit_logs` by time, move analytics to rollup tables or a read replica.

**28. What are the known weaknesses of the regex/`arguments_text` approach?** Regex policies can be bypassed by obfuscation (e.g., SQL comments between keywords) and complex regexes risk ReDoS (I cap length and validate at creation, but Python's `re` has no timeout). Structured rules (`arguments.<path>`) are safer; a real SQL parser or a RE2 engine would be the next step.

**29. What would you build next?** Default-deny per org; external anchoring of audit hashes; webhook/Slack notifications for approvals; per-tool/per-agent budgets (cumulative cost); SSO; OpenTelemetry tracing; a Python SDK that wraps evaluate → poll → verify-token; CSRF tokens; policy versioning with diff/rollback.

**30. What are the limitations you'd call out honestly?** Single approval step (no quorum/escalation); HS256 secrets in env (no key rotation/JWKS); rate limit and repeat state are lost if Redis loses data (fail-closed protects, but counters reset); audit append serialises per org; the one-time approval token lives only in Redis; no email invitations (admins create members with a temporary password); Docker images were written but should be built on your machine before relying on them.

## Known limitations & future improvements
See answers 19, 27, 28, 29, 30. Be upfront in interviews: these are conscious trade-offs, and you can describe how you'd address each.
