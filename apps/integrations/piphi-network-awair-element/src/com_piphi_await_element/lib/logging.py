import logging
import os
from typing import Any

logger = logging.getLogger("piphi.awair")
SENSITIVE_KEYS = {"token", "password", "secret", "authorization", "cookie", "key"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(part in str(key).lower() for part in SENSITIVE_KEYS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value

DEFAULT_LOG_FORMAT = (
    "ts=%(asctime)s level=%(levelname)s logger=%(name)s message=\"%(message)s\""
)
DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def configure_logging(level: str | None = None) -> None:
    """Configure a consistent logging format for the integration process."""
    log_level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()

    root = logging.getLogger()
    if not root.handlers:
        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT))
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT))

    root.setLevel(log_level)
    logger.setLevel(log_level)


def _format_log_value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    if not text:
        return '""'
    if any(ch.isspace() for ch in text) or '"' in text:
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


def log_event(event: str, level: str = "info", exc_info: bool = False, **fields: Any) -> None:
    fields = redact(fields)
    parts = [f"event={event}"]
    for key, value in fields.items():
        parts.append(f"{key}={_format_log_value(value)}")
    message = " ".join(parts)

    level_name = (level or "info").lower()
    log_method = getattr(logger, level_name, logger.info)
    log_method(message, exc_info=exc_info)


configure_logging()
