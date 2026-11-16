from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


REDACTED = "[redacted]"
SECRET_KEY_PARTS = (
    "access_token",
    "accesstoken",
    "app_key",
    "appkey",
    "auth_code",
    "authorization",
    "cookie",
    "internal_token",
    "password",
    "refresh_token",
    "refreshtoken",
    "secret",
    "token",
)
DIAGNOSTIC_PII_KEYS = {
    "account",
    "device_name",
    "did",
    "name",
    "open_id",
    "openid",
    "parent_did",
    "position_id",
    "subject_id",
    "subjectid",
    "trigger_source",
}


def redact_recursive(
    value: Any,
    *,
    secret_values: Iterable[str] = (),
    redact_pii: bool = False,
) -> Any:
    """Return a recursively redacted copy suitable for public output or logs."""

    secrets = tuple(
        sorted(
            {str(item) for item in secret_values if item is not None and len(str(item)) >= 4},
            key=len,
            reverse=True,
        )
    )

    def redact(item: Any, key: str | None = None) -> Any:
        normalized_key = str(key or "").strip().lower().replace("-", "_")
        if normalized_key and any(part in normalized_key for part in SECRET_KEY_PARTS):
            return REDACTED
        if redact_pii and normalized_key in DIAGNOSTIC_PII_KEYS:
            return REDACTED
        if isinstance(item, Mapping):
            return {str(child_key): redact(child_value, str(child_key)) for child_key, child_value in item.items()}
        if isinstance(item, (list, tuple, set, frozenset)):
            return [redact(child) for child in item]
        if isinstance(item, str):
            redacted = item
            for secret in secrets:
                redacted = redacted.replace(secret, REDACTED)
            return redacted
        return item

    return redact(value)
