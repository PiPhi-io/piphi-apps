from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any

SENSITIVE_KEYS = (
    "api_key", "authorization", "credential", "password", "secret",
    "serial_port", "signature", "token",
)
SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


def redact(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if any(part in key.lower() for part in SENSITIVE_KEYS):
        return "[redacted]"
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k), depth=depth + 1) for k, v in list(value.items())[:200]}
    if isinstance(value, (list, tuple)):
        return [redact(item, depth=depth + 1) for item in list(value)[:200]]
    if isinstance(value, bytes):
        return f"[binary:{len(value)}]"
    if isinstance(value, str) and len(value) > 4096:
        return value[:4096] + "[truncated]"
    return value


def safe_error_code(exc: BaseException) -> str:
    message = str(exc).strip()
    return message if SAFE_ERROR.fullmatch(message) else type(exc).__name__


def verify_profile_trust(*, digest: str, declared_digest: str | None, signature: str | None) -> None:
    anchor = os.getenv("PIPHI_MODBUS_PROFILE_TRUST_ANCHOR", "").strip()
    production = os.getenv("PIPHI_ENV", "").lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production"
    if not any((anchor, declared_digest, signature)) and not production:
        return
    if not anchor or not declared_digest or not signature:
        raise ValueError("trusted_profile_proof_required")
    if not hmac.compare_digest(digest, declared_digest.lower()):
        raise ValueError("profile_digest_mismatch")
    expected = hmac.new(anchor.encode(), digest.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise ValueError("profile_signature_invalid")
