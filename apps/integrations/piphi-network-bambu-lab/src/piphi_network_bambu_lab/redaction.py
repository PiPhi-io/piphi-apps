from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import SecretStr

SENSITIVE_KEYS = {
    "access_code",
    "accesscode",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
}


def redact(value: Any) -> Any:
    """Recursively remove credentials from diagnostic and event-shaped values."""
    if isinstance(value, SecretStr):
        return "********"
    if isinstance(value, Mapping):
        return {
            str(key): ("********" if str(key).lower() in SENSITIVE_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value
