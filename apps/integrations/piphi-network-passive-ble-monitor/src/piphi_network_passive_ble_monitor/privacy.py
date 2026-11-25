from __future__ import annotations

from typing import Any

SENSITIVE_PARTS = (
    "authorization",
    "bind_key",
    "bindkey",
    "cookie",
    "credential",
    "gateway_url",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
)


def redact(value: Any) -> Any:
    """Recursively remove secret-bearing values before they leave the process."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if any(part in str(key).lower() for part in SENSITIVE_PARTS)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    return value
