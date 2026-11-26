from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import SecretStr

REDACTED = "[redacted]"
SENSITIVE_KEYS = {
    "access_token",
    "authorization",
    "cookie",
    "email",
    "mfa_code",
    "mfa_token",
    "password",
    "refresh_token",
    "secret",
    "token",
    "user_id",
}
_INLINE_SECRET = re.compile(
    r"(?i)(access_token|authorization|cookie|email|mfa_code|mfa_token|password|refresh_token|secret|token|user_id)"
    r"([=:]\s*)([^\s,;&]+)"
)


def redact(value: Any, *, key: str | None = None, secrets: Sequence[str] = ()) -> Any:
    """Return a recursively sanitized copy for logs and runtime responses."""
    known = tuple(item for item in secrets if item)
    if key and key.lower() in SENSITIVE_KEYS and value not in (None, ""):
        return REDACTED
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item, key=str(item_key), secrets=known)
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item, secrets=known) for item in value]
    if isinstance(value, str):
        sanitized = _INLINE_SECRET.sub(r"\1\2[redacted]", value)
        for secret in known:
            sanitized = sanitized.replace(secret, REDACTED)
        return sanitized
    return value


class SecretScrubbingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = str(redact(str(record.msg)))
        if record.args:
            record.args = redact(record.args)
        return True


def install_log_scrubbing() -> None:
    scrubber = SecretScrubbingFilter()
    for logger_name in ("", "aiohttp", "sense_energy", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        if not any(isinstance(item, SecretScrubbingFilter) for item in logger.filters):
            logger.addFilter(scrubber)
        for handler in logger.handlers:
            if not any(isinstance(item, SecretScrubbingFilter) for item in handler.filters):
                handler.addFilter(scrubber)
