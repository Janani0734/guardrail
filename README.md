# GuardRail - Runtime Approval Gateway for AI Agents

[![CI](https://github.com/Janani0734/guardrail/actions/workflows/ci.yml/badge.svg)](https://github.com/Janani0734/guardrail/actions/workflows/ci.yml) ![Tests](https://img.shields.io/badge/tests-96%20backend%20%2B%2022%20frontend-brightgreen) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-009688) ![Next.js](https://img.shields.io/badge/Next.js-14-black) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

▶️ **[Watch the demo video](https://drive.google.com/file/d/1zVAl44yz5jg2VCouynGCHylcFmeQynmO/view?usp=sharing)**

GuardRail sits between an AI agent and the action it wants to perform. For every request it answers **ALLOW**, **BLOCK** or **REQUIRE_APPROVAL**; risky actions wait in a dashboard queue for a human, expire if nobody answers, and every decision lands in a tamper-evident audit log.

```
agent ──POST /v1/actions/evaluate (X-API-Key)──▶ GuardRail ──▶ ALLOW | BLOCK | REQUIRE_APPROVAL
                                                    │  PostgreSQL = source of truth
                                                    │  Redis = rate limits, repeat counters, approval state/tokens, cache
admin ──Next.js dashboard──▶ approve / reject / manage policies, agents, tools, keys
```

## Architecture

```mermaid
flowchart LR
  A[AI agent] -- "POST /v1/actions/evaluate<br/>X-API-Key" --> API[FastAPI gateway]
  UI[Next.js dashboard<br/>httpOnly-cookie proxy] -- JWT --> API
  API --> PE[Policy engine<br/>block > approval > allow]
  PE --> D{Decision}
  D -->|ALLOW| A
  D -->|BLOCK| A
  D -->|REQUIRE_APPROVAL| Q[(Approval queue)]
  Q -->|human approves / rejects| UI
  API --> PG[(PostgreSQL<br/>source of truth + hash-chained audit log)]
  API --> R[(Redis<br/>rate limits, repeat counters,<br/>approval tokens, cache)]
  W[Expiry worker] --> Q
```

More detail in [ARCHITECTURE.md](ARCHITECTURE.md).

## Screenshots

| | |
|---|---|
| **Overview** ![Overview](docs/screenshots/dashboard.png) | **Pending approvals** ![Approvals](docs/screenshots/approvals.png) |
| **Policies** ![Policies](docs/screenshots/policies.png) | **Audit logs** ![Audit logs](docs/screenshots/audit-logs.png) |
| **Analytics** ![Analytics](docs/screenshots/analytics.png) | **API docs (Swagger)** ![API docs](docs/screenshots/api-docs.png) |

## Features
- Agent registration, per-agent tool permissions, hashed API keys (shown once, revocable, expirable)
- Policy engine: block tool (global / per environment), require approval (tool / cost / production), rate limit, block unknown tools, repeated failed-or-blocked action guard, regex on arguments, policy **simulation**
- Human approval workflow with reasons, one-time approval tokens and automatic expiry (background worker)
- Secret detection and redaction before anything is stored
- Hash-chained, append-only audit log (+ DB trigger + integrity check endpoint)
- JWT access/refresh auth, organizations, ADMIN / MANAGER / VIEWER roles, IDOR-safe tenant scoping
- Dashboard: overview, agents, keys, tools, policies, approvals, history with filters, audit logs, analytics charts, settings

## Tech stack
Python 3.11+ · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · pydantic-settings · PostgreSQL 16 · Redis 7 · Pytest ·
Next.js 14 (App Router) · React 18 · TypeScript (strict) · Tailwind CSS · Zod · TanStack Query · Recharts · Docker Compose

## Quick start (local)

Prerequisites: Docker, Python 3.11+, Node 20+.

```bash
# 1. PostgreSQL + Redis
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                      # defaults match docker-compose.yml
alembic upgrade head
python -m scripts.seed                                    # demo data
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
cp .env.example .env.local                                # BACKEND_URL=http://localhost:8000
npm install
npm run dev                                               # http://localhost:3000
```

**Windows (Command Prompt)** — use these instead of the `source` and `cp` lines above:
```bat
python -m venv .venv
.venv\Scripts\activate
copy .env.example .env
```
(Frontend: `copy .env.example .env.local`.)

API docs (Swagger): http://localhost:8000/docs · Health: http://localhost:8000/health

### Everything in Docker
```bash
docker compose --profile full up -d --build
docker compose exec backend python -m scripts.seed
```
Dashboard http://localhost:3000, API http://localhost:8000. (Migrations run automatically when the backend container starts.)

### Tests
```bash
cd backend
pytest                      # 96 tests, hermetic: SQLite + fakeredis, ~1 min
# same suite on real PostgreSQL (the target database is dropped/recreated per test!):
docker compose exec postgres psql -U guardrail -c "CREATE DATABASE guardrail_test"
TEST_DATABASE_URL=postgresql+asyncpg://guardrail:guardrail@localhost:5432/guardrail_test pytest
```
Frontend (Vitest + React Testing Library, 22 tests): `npm test`, plus `npm run typecheck` and `npm run build`.

## Demo credentials (local use only)
> ⚠️ These credentials and API keys are for local development only. Never use them in production; change all secrets before deploying.

| Role | Email | Password |
|------|-------|----------|
| ADMIN | admin@guardrail.demo | `Demo@12345!` |
| MANAGER | manager@guardrail.demo | `Demo@12345!` |
| VIEWER | viewer@guardrail.demo | `Demo@12345!` |

Demo agent API keys (fixed so the examples below work — never use fixed keys outside a laptop):
`support-agent-01` → `grk_demo_support_agent_01_local_only_0001`, `billing-agent-02` → `…_0002`, `devops-agent-03` → `…_0003`.

## API examples
```bash
KEY=grk_demo_support_agent_01_local_only_0001

# BLOCK: delete_database_records is forbidden in production
curl -s -X POST localhost:8000/v1/actions/evaluate -H "X-API-Key: $KEY" -H 'content-type: application/json' -d '{
  "agent_id":"support-agent-01","action_id":"act_123","tool":"delete_database_records","environment":"production",
  "arguments":{"table":"old_logs","limit":1000},"estimated_cost":12.5,"reason":"Clean expired log records"}'

# REQUIRE_APPROVAL (HTTP 202): cost > 10
curl -s -X POST localhost:8000/v1/actions/evaluate -H "X-API-Key: $KEY" -H 'content-type: application/json' -d '{
  "agent_id":"support-agent-01","action_id":"act_124","tool":"send_email","environment":"production",
  "arguments":{"to":"all-customers@example.com"},"estimated_cost":15}'

# poll until a human decides (an approval token appears once, after approval)
curl -s localhost:8000/v1/actions/act_124/status -H "X-API-Key: $KEY"
```
Then open **Pending approvals** in the dashboard and approve or reject. Full reference: [API.md](API.md).

## Project layout
```
GuardRail/
├─ docker-compose.yml
├─ backend/   app/{core,models,schemas,repositories,services,routers,workers,utils}, alembic/, scripts/seed.py, tests/
└─ frontend/  src/{app,components,hooks,lib,types,styles}
```
Documentation: [ARCHITECTURE.md](ARCHITECTURE.md) · [API.md](API.md) · [CHANGELOG.md](CHANGELOG.md)

## Known limitations
- Single approval step (no quorum or escalation chains)
- JWT uses HS256 with secrets from env (no key rotation / JWKS)
- Rate-limit and repeat-block counters live in Redis; if Redis loses data they reset (the gateway fails closed while Redis is down)
- The audit hash chain makes tampering *detectable*, not impossible; anchoring the latest hash externally would harden it
- The one-time approval token is stored only in Redis
- No email invitations: admins create members with a temporary password
- Secret redaction is pattern/key-name based, so an unlabelled arbitrary secret can slip through


## License
MIT, see [LICENSE](LICENSE).

## Troubleshooting
| Symptom | Fix |
|---|---|
| `connection refused` on 5432/6379 | `docker compose up -d`, then `docker compose ps` (wait for *healthy*) |
| Port 5432 or 6379 already in use | Stop the local Postgres/Redis, or change the host port in `docker-compose.yml` and your `.env` URLs |
| `port is already allocated` for 6379 when starting Docker | Another Redis (for example from a different project) holds the port. Find it with `docker ps`, stop it (`docker stop <name>`), or change the host port in `docker-compose.yml` (e.g. `"6382:6379"`; the containers still talk to each other on 6379) |
| Backend logs `expiry worker cannot reach redis` in Docker | The Redis container is not on the compose network (usually after a failed start). Run `docker compose --profile full up -d --force-recreate redis` then `docker compose --profile full restart backend` |
| `alembic upgrade head` fails to connect | Check `DATABASE_URL` in `backend/.env` (must use the `postgresql+asyncpg://` scheme) |
| Dashboard shows “Cannot reach the GuardRail API” | Backend not running, or `BACKEND_URL` in `frontend/.env.local` is wrong; restart `npm run dev` after editing env |
| Seed says “already exists” | `alembic downgrade base && alembic upgrade head`, then seed again (audit rows are append-only, so a reset recreates the schema) |
| Seeded “pending approvals” are gone | They expire after ~30 minutes by design. Send a new request (see API examples) or re-seed |
| 429 from the evaluate endpoint | You hit a rate-limit policy (20/min in the seed). Read the `Retry-After` header |
| 503 `STATE_STORE_UNAVAILABLE` | Redis is down. GuardRail fails closed rather than guessing |
| Login blocked with 429 | 10 failed attempts / 5 min per email. Wait or `redis-cli DEL login_attempts:<email>` |
| `bcrypt`/`asyncpg` build errors on Windows | Use Python 3.11/3.12 (wheels are published); upgrade pip |
