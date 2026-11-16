from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = (
    "access_token",
    "address",
    "alias",
    "authorization",
    "credential",
    "device_name",
    "email",
    "home_name",
    "household",
    "ip_address",
    "location",
    "password",
    "pat",
    "raw",
    "secret",
    "ssid",
    "token",
)
_IP_ADDRESS = re.compile(r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])")
_EMAIL_ADDRESS = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")


def _sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_sensitive(value: Any, *, secrets: Sequence[str] = ()) -> Any:
    """Return a recursively sanitized copy suitable for events and public output."""
    secret_values = tuple(secret for secret in secrets if secret)
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _sensitive_key(key) else redact_sensitive(item, secrets=secret_values)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_sensitive(item, secrets=secret_values) for item in value]
    if isinstance(value, str):
        sanitized = value
        for secret in secret_values:
            sanitized = sanitized.replace(secret, REDACTED)
        sanitized = _EMAIL_ADDRESS.sub(REDACTED, sanitized)
        return _IP_ADDRESS.sub(REDACTED, sanitized)
    return value


def private_identifier(value: Any) -> str:
    """Provide stable diagnostic correlation without exposing an identifier."""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"
