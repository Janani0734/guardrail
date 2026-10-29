import base64
import hashlib
import json
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import Unauthorized

API_KEY_PREFIX = "grk_"


def _prehash(password: str) -> bytes:
    # bcrypt only reads the first 72 bytes; pre-hashing removes that silent truncation.
    return base64.b64encode(hashlib.sha256(password.encode()).digest())


def hash_password(password: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode())
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def _encode(payload: dict[str, Any]) -> str:
    s = get_settings()
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID) -> tuple[str, int]:
    s = get_settings()
    now = _now()
    exp = now + timedelta(minutes=s.access_token_minutes)
    token = _encode(
        {"sub": str(user_id), "org": str(org_id), "type": "access", "jti": uuid.uuid4().hex,
         "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    )
    return token, s.access_token_minutes * 60


def create_refresh_token(user_id: uuid.UUID, org_id: uuid.UUID) -> tuple[str, str, datetime]:
    s = get_settings()
    now = _now()
    exp = now + timedelta(days=s.refresh_token_days)
    jti = uuid.uuid4().hex
    token = _encode(
        {"sub": str(user_id), "org": str(org_id), "type": "refresh", "jti": jti,
         "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    )
    return token, jti, exp


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Token has expired", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Invalid token", code="INVALID_TOKEN") from exc
    if payload.get("type") != expected_type:
        raise Unauthorized("Wrong token type", code="INVALID_TOKEN")
    return payload


def _hmac(value: str) -> str:
    return hmac.new(get_settings().api_key_pepper.encode(), value.encode(), hashlib.sha256).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, display_prefix, hmac_hash). The raw key is shown exactly once."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:12], _hmac(raw)


def hash_api_key(raw: str) -> str:
    return _hmac(raw)


def fingerprint(value: str) -> str:
    """Keyed hash used for action fingerprints, so low-entropy arguments can't be dictionary-attacked."""
    return _hmac("fp:" + value)


def action_fingerprint(tool: str, environment: str, arguments: dict) -> str:
    """Keyed hash of exactly what an agent asked to do (tool + environment + raw arguments).

    Computed when an action is evaluated and recomputed when an approval token is redeemed, so a token can only
    authorise the very request a human approved."""
    return fingerprint(f"{tool}|{environment.lower()}|{json.dumps(arguments, sort_keys=True, default=str)}")


def generate_approval_token() -> str:
    return "apt_" + secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
