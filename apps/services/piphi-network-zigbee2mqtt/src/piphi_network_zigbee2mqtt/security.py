from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[redacted]"
_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|token|secret|password|credential|network[_-]?key|private[_-]?key|"
    r"client[_-]?(?:key|cert)|certificate|mqtt[_-]?(?:password|username)|pan[_-]?id|"
    r"ext[_-]?pan[_-]?id|ieee(?:_address)?|serial[_-]?number)"
)
_INLINE_SECRET = re.compile(
    r"(?i)(authorization|token|secret|password|network[_-]?key|private[_-]?key)=([^&\s]+)"
)


def redact(value: Any, *, key: str | None = None) -> Any:
    if key and _SENSITIVE_KEY.search(key) and value not in (None, ""):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _INLINE_SECRET.sub(r"\1=[redacted]", value)
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
