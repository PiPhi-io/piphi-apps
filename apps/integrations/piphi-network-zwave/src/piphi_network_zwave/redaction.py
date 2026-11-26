from __future__ import annotations

import re
from typing import Any

_SENSITIVE = re.compile(r"s0|s2|security|network.?key|credential|token|secret|password|dsk|pin|raw.?frame|nvm|private", re.I)


def redact(value: Any, key: str = "") -> Any:
    if _SENSITIVE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(child): redact(item, str(child)) for child, item in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [redact(item, key) for item in list(value)[:100]]
    if isinstance(value, str) and len(value) > 4096:
        return value[:4096] + "[truncated]"
    return value
