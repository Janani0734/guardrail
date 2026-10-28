"""Single place that defines every Redis key so the keyspace is documented and greppable."""
import uuid


def rate_limit(scope: str, scope_id: uuid.UUID, policy_ref: str) -> str:
    return f"rl:{scope}:{scope_id}:{policy_ref}"


def repeat_counter(org_id: uuid.UUID, agent_id: uuid.UUID, fp: str) -> str:
    return f"repeat:{org_id}:{agent_id}:{fp}"


def temp_block(org_id: uuid.UUID, agent_id: uuid.UUID, fp: str) -> str:
    return f"tempblock:{org_id}:{agent_id}:{fp}"


def approval_state(approval_id: uuid.UUID) -> str:
    return f"approval:{approval_id}"


def approval_token(token_hash: str) -> str:
    return f"approval_token:{token_hash}"


def revoked_jti(jti: str) -> str:
    return f"revoked_jti:{jti}"


def login_attempts(email: str) -> str:
    return f"login_attempts:{email.lower()}"


def analytics_version(org_id: uuid.UUID) -> str:
    return f"analytics:ver:{org_id}"


def analytics_cache(org_id: uuid.UUID, version: str, kind: str, days: int) -> str:
    return f"analytics:{org_id}:v{version}:{kind}:{days}"


EXPIRY_LOCK = "lock:approval-expiry"
