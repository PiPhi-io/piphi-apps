from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr

REDACTED = "********"
SENSITIVE_KEYS = {
    "api_key", "key", "password", "secret", "token", "access_token",
    "refresh_token", "authorization", "device_udid", "udid",
}
_QUERY_SECRET = re.compile(r"([?&](?:key|api_key|token|access_token)=)[^&\s]+", re.IGNORECASE)


def scrub_url(value: str) -> str:
    """Remove query credentials without changing the safe request path."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _QUERY_SECRET.sub(r"\1********", value)
    if not parsed.query:
        return _QUERY_SECRET.sub(r"\1********", value)
    query = urlencode([
        (key, REDACTED if key.lower() in SENSITIVE_KEYS else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def redact(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact secrets in diagnostics, events, and log context."""
    if key and key.lower() in SENSITIVE_KEYS and value not in (None, ""):
        return REDACTED
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return scrub_url(value)
    return value


class SecretScrubbingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub_url(str(record.msg))
        if record.args:
            record.args = tuple(redact(item) for item in record.args) if isinstance(record.args, tuple) else redact(record.args)
        return True


def install_log_scrubbing() -> None:
    root = logging.getLogger()
    scrubber = SecretScrubbingFilter()
    for logger_name in ("", "httpx", "httpcore", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        if not any(isinstance(item, SecretScrubbingFilter) for item in logger.filters):
            logger.addFilter(scrubber)
        for handler in logger.handlers:
            if not any(isinstance(item, SecretScrubbingFilter) for item in handler.filters):
                handler.addFilter(scrubber)
    # httpx's normal INFO request log includes the full URL. Production code
    # reports typed outcomes itself, so suppress that unsafe duplicate record.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
