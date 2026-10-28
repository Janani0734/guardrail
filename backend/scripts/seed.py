"""Seed a demo organisation:  python -m scripts.seed

Creates 1 org, 3 users (admin/manager/viewer), 3 agents with API keys, 8 tools, 9 policies and ~150 sample actions
spread over the last 7 days (decisions come from the real policy engine), plus approvals in every state and a
hash-chained audit trail. Idempotent: refuses to run twice. To start over: alembic downgrade base && alembic upgrade head.

DEMO CREDENTIALS ARE FOR LOCAL USE ONLY.
"""
import asyncio
import random
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.database import get_engine, get_sessionmaker
from app.core.security import fingerprint, hash_api_key, hash_password
from app.models import (
    ActionRequest, Agent, AgentTool, ApiKey, Approval, Membership, Organization, Policy, PolicyDecision, PolicyRule,
    RateLimitEvent, Tool, User,
)
from app.models.base import utcnow
from app.models.enums import (
    ActionStatus, ActorType, ApprovalStatus, Decision, PolicyType, RiskLevel, Role, RuleOperator,
)
from app.services.audit_service import AuditService
from app.services.policy_engine import ActionContext, evaluate
from app.utils.redaction import redact_text, redact_value

DEMO_PASSWORD = "Demo@12345!"
ORG_SLUG = "demo-corp"
USERS = [("admin@guardrail.demo", "Ada Admin", Role.ADMIN), ("manager@guardrail.demo", "Max Manager", Role.MANAGER),
         ("viewer@guardrail.demo", "Vera Viewer", Role.VIEWER)]
AGENTS = {
    "support-agent-01": ("Support Agent", "Answers tickets, reads logs, sends customer emails",
                         "grk_demo_support_agent_01_local_only_0001", ["read_logs", "send_email", "search_kb", "delete_database_records"]),
    "billing-agent-02": ("Billing Agent", "Issues refunds and reconciles invoices",
                         "grk_demo_billing_agent_02_local_only_0002", ["issue_refund", "read_logs", "send_email", "run_sql"]),
    "devops-agent-03": ("DevOps Agent", "Deploys services and maintains databases",
                        "grk_demo_devops_agent_03_local_only_0003", ["deploy_service", "run_sql", "read_logs", "delete_database_records"]),
}
TOOLS = [("read_logs", RiskLevel.LOW, "Read application logs"), ("search_kb", RiskLevel.LOW, "Search the knowledge base"),
         ("send_email", RiskLevel.MEDIUM, "Send an email to a customer"), ("issue_refund", RiskLevel.HIGH, "Refund a payment"),
         ("run_sql", RiskLevel.HIGH, "Execute a SQL statement"), ("deploy_service", RiskLevel.HIGH, "Deploy a service"),
         ("delete_database_records", RiskLevel.HIGH, "Delete rows from a table"), ("format_disk", RiskLevel.CRITICAL, "Format a disk")]
R = RuleOperator


def rule(f, op, v):
    return (f, op, v)


POLICIES = [
    dict(name="Never allow DROP TABLE", priority=5, effect=Decision.BLOCK, reason_code="DROP_TABLE_FORBIDDEN",
         message="DROP TABLE is always blocked", rules=[rule("arguments_text", R.REGEX, r"\bDROP\s+TABLE\b")]),
    dict(name="Block format_disk globally", priority=10, effect=Decision.BLOCK, reason_code="FORBIDDEN_TOOL",
         message="Tool format_disk is blocked everywhere", rules=[rule("tool", R.EQ, "format_disk")]),
    dict(name="Block delete_database_records in production", priority=20, effect=Decision.BLOCK,
         reason_code="FORBIDDEN_TOOL_IN_PRODUCTION", message="Tool delete_database_records is blocked in production",
         rules=[rule("tool", R.EQ, "delete_database_records"), rule("environment", R.EQ, "production")]),
    dict(name="Production DELETE/DROP/TRUNCATE needs approval", priority=30, effect=Decision.REQUIRE_APPROVAL,
         reason_code="DESTRUCTIVE_SQL_IN_PRODUCTION", message="Destructive SQL in production requires admin approval",
         rules=[rule("environment", R.EQ, "production"), rule("arguments_text", R.REGEX, r"\b(DELETE|DROP|TRUNCATE)\b")]),
    dict(name="Costly actions need approval", priority=40, effect=Decision.REQUIRE_APPROVAL, reason_code="HIGH_COST",
         message="High-cost action requires admin approval", rules=[rule("estimated_cost", R.GT, 10)]),
    dict(name="Bulk refunds in production need approval", priority=50, effect=Decision.REQUIRE_APPROVAL,
         reason_code="PROD_REFUND_APPROVAL", message="Production refunds require approval",
         rules=[rule("tool", R.IN, ["issue_refund", "deploy_service"]), rule("environment", R.EQ, "production")]),
    dict(name="Block unknown tools", priority=60, effect=Decision.BLOCK, type=PolicyType.UNKNOWN_TOOL,
         reason_code="UNKNOWN_TOOL", message="Unknown tools are blocked", rules=[]),
    dict(name="20 actions per minute per agent", priority=70, effect=Decision.BLOCK, type=PolicyType.RATE_LIMIT,
         reason_code="RATE_LIMIT_EXCEEDED", config={"limit": 20, "window_seconds": 60, "scope": "agent"}, rules=[]),
    dict(name="Same failed action 3 times -> 5 min block", priority=80, effect=Decision.BLOCK,
         type=PolicyType.REPEATED_ACTION, reason_code="REPEATED_ACTION_BLOCKED",
         config={"threshold": 3, "window_seconds": 600, "block_seconds": 300}, rules=[]),
]

SCENARIOS = [  # (weight, tool, env, args, cost, reason)
    (30, "read_logs", ["staging", "production", "development"], {"service": "api", "lines": 200}, (0, 2), "Investigate error spike"),
    (12, "search_kb", ["production"], {"query": "refund policy"}, (0, 1), "Answer customer question"),
    (14, "send_email", ["production", "staging"], {"to": "customer@example.com", "template": "ticket_update"}, (0, 3), "Notify customer"),
    (10, "issue_refund", ["production", "staging"], {"order": "ORD-1042", "amount": 40}, (1, 25), "Customer refund"),
    (9, "run_sql", ["production", "staging"], {"sql": "SELECT count(*) FROM orders"}, (0, 4), "Daily report"),
    (6, "run_sql", ["production", "staging"], {"sql": "DELETE FROM sessions WHERE expired = true"}, (1, 6), "Cleanup sessions"),
    (3, "run_sql", ["production"], {"sql": "DROP TABLE temp_import"}, (0, 1), "Remove scratch table"),
    (7, "deploy_service", ["production", "staging"], {"service": "checkout", "version": "2.4.1"}, (2, 14), "Ship release"),
    (6, "delete_database_records", ["production", "staging"], {"table": "old_logs", "limit": 1000}, (1, 13), "Clean expired log records"),
    (2, "format_disk", ["staging"], {"device": "/dev/sdb"}, (0, 1), "Reclaim space"),
    (4, "launch_missiles", ["production"], {"target": "moon"}, (0, 1), "Experiment"),
    (3, "send_email", ["production"], {"to": "ops@example.com", "api_key": "sk_" + "live_51HxExampleSecretKey00001", "note": "token=ghp_" + "x" * 36},
     (0, 2), "Send report using password=SuperSecret99"),
]


async def main() -> None:
    rnd = random.Random(42)
    async with get_sessionmaker()() as s:
        if (await s.execute(select(Organization).where(Organization.slug == ORG_SLUG))).scalar_one_or_none():
            print("Demo organisation already exists - nothing to do.")
            return
        now = utcnow()
        t0 = now - timedelta(days=8)
        org = Organization(name="Demo Corp", slug=ORG_SLUG, created_at=t0, updated_at=t0)
        s.add(org)
        await s.flush()
        audit = AuditService(s)
        await audit.log(org_id=org.id, actor_type=ActorType.SYSTEM, actor_label="seed", event_type="ORGANIZATION_CREATED",
                        entity_type="organization", entity_id=org.id, details={"name": org.name}, created_at=t0)

        users: dict[Role, User] = {}
        for email, name, role in USERS:
            u = User(email=email, password_hash=hash_password(DEMO_PASSWORD), full_name=name, created_at=t0, updated_at=t0)
            s.add(u)
            await s.flush()
            s.add(Membership(organization_id=org.id, user_id=u.id, role=role))
            users[role] = u
            await audit.log(org_id=org.id, actor_type=ActorType.SYSTEM, actor_label="seed", event_type="MEMBER_ADDED",
                            entity_type="user", entity_id=u.id, details={"email": email, "role": role.value}, created_at=t0)

        tools = {}
        for name, risk, desc in TOOLS:
            t = Tool(organization_id=org.id, name=name, risk_level=risk, description=desc, created_at=t0, updated_at=t0)
            s.add(t)
            tools[name] = t
        await s.flush()

        agents: dict[str, tuple[Agent, ApiKey]] = {}
        for slug, (name, desc, raw_key, tool_names) in AGENTS.items():
            a = Agent(organization_id=org.id, slug=slug, name=name, description=desc, created_at=t0, updated_at=t0)
            s.add(a)
            await s.flush()
            k = ApiKey(organization_id=org.id, agent_id=a.id, name="demo key", prefix=raw_key[:12],
                       key_hash=hash_api_key(raw_key), created_by=users[Role.ADMIN].id, created_at=t0, updated_at=t0)
            s.add(k)
            for tn in tool_names:
                s.add(AgentTool(agent_id=a.id, tool_id=tools[tn].id))
            await s.flush()
            agents[slug] = (a, k)
            await audit.log(org_id=org.id, actor_type=ActorType.USER, actor_id=users[Role.ADMIN].id,
                            actor_label=users[Role.ADMIN].email, event_type="AGENT_CREATED", entity_type="agent",
                            entity_id=a.id, details={"slug": slug}, created_at=t0)

        policies = []
        for spec in POLICIES:
            p = Policy(organization_id=org.id, name=spec["name"], policy_type=spec.get("type", PolicyType.RULE),
                       effect=spec["effect"], priority=spec["priority"], reason_code=spec["reason_code"],
                       message=spec.get("message"), config=spec.get("config", {}), created_at=t0, updated_at=t0,
                       rules=[PolicyRule(position=i, field=f, operator=op, value=v) for i, (f, op, v) in enumerate(spec["rules"])])
            s.add(p)
            policies.append(p)
        await s.flush()
        for p in policies:
            await audit.log(org_id=org.id, actor_type=ActorType.USER, actor_id=users[Role.ADMIN].id,
                            actor_label=users[Role.ADMIN].email, event_type="POLICY_CREATED", entity_type="policy",
                            entity_id=p.id, details={"name": p.name, "effect": p.effect.value}, created_at=t0)

        # ---- sample traffic, oldest first so the audit chain is chronological
        weights = [sc[0] for sc in SCENARIOS]
        stamps = sorted(now - timedelta(seconds=rnd.randint(60 * 20, 7 * 86400)) for _ in range(150))
        admin, manager = users[Role.ADMIN], users[Role.MANAGER]
        counter = 0

        async def record(ts, slug, tool_name, env, args, cost, reason, force_pending=False):
            nonlocal counter
            counter += 1
            agent, key = agents[slug]
            assigned = {tn for tn in AGENTS[slug][3]}
            known = tool_name in tools
            permitted = known and tool_name in assigned
            ctx = ActionContext(agent_id=slug, tool=tool_name, environment=env, estimated_cost=float(cost), reason=reason,
                                arguments=args, tool_known=known, tool_permitted=permitted)
            res = evaluate(ctx, policies)
            safe_args, n1 = redact_value(args)
            safe_reason, n2 = redact_text(reason)
            status = {Decision.ALLOW: ActionStatus.ALLOWED, Decision.BLOCK: ActionStatus.BLOCKED,
                      Decision.REQUIRE_APPROVAL: ActionStatus.PENDING_APPROVAL}[res.decision]
            ar = ActionRequest(
                organization_id=org.id, agent_id=agent.id, api_key_id=key.id, action_id=f"act_{counter:05d}", tool=tool_name,
                environment=env, arguments=safe_args, estimated_cost=Decimal(str(cost)), reason=safe_reason,
                fingerprint=fingerprint(f"{tool_name}|{env}|{sorted(args.items())}"), secrets_redacted=n1 + n2,
                decision=res.decision, status=status, reason_code=res.reason_code, latency_ms=rnd.randint(3, 18),
                created_at=ts, updated_at=ts)
            s.add(ar)
            await s.flush()
            s.add(PolicyDecision(organization_id=org.id, action_request_id=ar.id, policy_id=res.policy.id if res.policy else None,
                                 decision=res.decision, reason_code=res.reason_code, message=res.message, trace=res.trace,
                                 created_at=ts, updated_at=ts))
            approval = None
            if res.decision == Decision.REQUIRE_APPROVAL:
                if force_pending:
                    approval = Approval(organization_id=org.id, action_request_id=ar.id, policy_id=res.policy.id,
                                        status=ApprovalStatus.PENDING, message=res.message,
                                        expires_at=now + timedelta(minutes=rnd.randint(12, 28)), created_at=ts, updated_at=ts)
                else:
                    outcome = rnd.choices([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED], [60, 25, 15])[0]
                    decided = ts + timedelta(minutes=rnd.randint(2, 20)) if outcome != ApprovalStatus.EXPIRED else ts + timedelta(minutes=30)
                    approval = Approval(
                        organization_id=org.id, action_request_id=ar.id, policy_id=res.policy.id, status=outcome,
                        message=res.message, expires_at=ts + timedelta(minutes=30), created_at=ts, updated_at=decided,
                        decided_by=None if outcome == ApprovalStatus.EXPIRED else rnd.choice([admin, manager]).id,
                        decided_at=decided,
                        decision_reason={"APPROVED": "Reviewed and safe", "REJECTED": "Not justified", "EXPIRED": "Expired without a decision"}[outcome.value])
                    ar.status = ActionStatus[outcome.value]
                s.add(approval)
                await s.flush()
            await audit.log(org_id=org.id, actor_type=ActorType.AGENT, actor_id=agent.id, actor_label=slug,
                            event_type="ACTION_EVALUATED", entity_type="action_request", entity_id=ar.id,
                            details={"action_id": ar.action_id, "tool": tool_name, "environment": env,
                                     "decision": res.decision.value, "reason_code": res.reason_code,
                                     "policy_id": str(res.policy.id) if res.policy else None, "secrets_redacted": n1 + n2,
                                     "approval_id": str(approval.id) if approval else None}, created_at=ts)
            if approval and approval.status != ApprovalStatus.PENDING:
                actor = next((u for u in (admin, manager) if u.id == approval.decided_by), None)
                await audit.log(
                    org_id=org.id, actor_type=ActorType.USER if actor else ActorType.SYSTEM, actor_id=actor.id if actor else None,
                    actor_label=actor.email if actor else "approval-expiry-worker",
                    event_type=f"APPROVAL_{approval.status.value}", entity_type="approval", entity_id=approval.id,
                    details={"action_id": ar.action_id, "tool": tool_name, "reason": approval.decision_reason}, created_at=approval.decided_at)

        for ts in stamps:
            _, tool_name, envs, args, (lo, hi), reason = rnd.choices(SCENARIOS, weights)[0]
            slug = rnd.choice([sl for sl, v in AGENTS.items() if tool_name in v[3]] or list(AGENTS))
            await record(ts, slug, tool_name, rnd.choice(envs), dict(args), round(rnd.uniform(lo, hi), 2), reason)

        for i, (slug, tool_name, args, cost, reason) in enumerate([
            ("billing-agent-02", "issue_refund", {"order": "ORD-2201", "amount": 180}, 30, "Refund duplicate charge"),
            ("devops-agent-03", "deploy_service", {"service": "payments", "version": "3.0.0"}, 12, "Release payments 3.0"),
            ("devops-agent-03", "run_sql", {"sql": "DELETE FROM audit_staging WHERE age > 90"}, 5, "Prune staging audit"),
            ("support-agent-01", "send_email", {"to": "all-customers@example.com", "template": "incident"}, 15, "Incident notice"),
        ]):
            await record(now - timedelta(minutes=3 + i * 4), slug, tool_name, "production", args, cost, reason, force_pending=True)

        for slug in ("support-agent-01", "devops-agent-03"):
            a, k = agents[slug]
            s.add(RateLimitEvent(organization_id=org.id, agent_id=a.id, api_key_id=k.id, policy_id=policies[7].id, scope="agent",
                                 limit=20, window_seconds=60, observed=21, created_at=now - timedelta(hours=rnd.randint(2, 40))))
        await s.commit()

    print("Seeded demo organisation 'Demo Corp'.")
    print(f"  Users (password: {DEMO_PASSWORD}):")
    for email, _, role in USERS:
        print(f"    {role.value:8} {email}")
    print("  Demo agent API keys (local use only):")
    for slug, (_, _, raw, _) in AGENTS.items():
        print(f"    {slug:18} {raw}")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
