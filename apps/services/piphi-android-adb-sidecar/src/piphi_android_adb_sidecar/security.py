from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "********"
SENSITIVE_KEYS = frozenset(
    {"authorization", "token", "internal_token", "pairing_code", "pin", "password", "secret", "adbkey"}
)
_INLINE_SECRET = re.compile(
    r"(?i)(authorization|token|pairing[_-]?code|pin|password|secret)=([^&\s]+)"
)


def redact(value: Any, *, key: str | None = None) -> Any:
    if key and key.lower() in SENSITIVE_KEYS and value not in (None, ""):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _INLINE_SECRET.sub(r"\1=********", value)
    return value


class SecretScrubbingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = str(redact(str(record.msg)))
        if record.args:
            record.args = redact(record.args)
        return True


def install_log_scrubbing() -> None:
    scrubber = SecretScrubbingFilter()
    for name in ("", "httpx", "httpcore", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, SecretScrubbingFilter) for item in logger.filters):
            logger.addFilter(scrubber)
        for handler in logger.handlers:
            if not any(isinstance(item, SecretScrubbingFilter) for item in handler.filters):
                handler.addFilter(scrubber)
