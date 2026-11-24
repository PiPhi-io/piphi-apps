from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
from typing import Any

from pydantic import SecretStr

SENSITIVE_KEYS = frozenset({"password", "username", "token", "secret", "credentials", "authorization"})


def redact(value: Any) -> Any:
    """Recursively remove credentials from values crossing the runtime boundary."""
    if isinstance(value, SecretStr):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if str(key).lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    return value


def diagnostic_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _is_permitted_local_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return bool(ip.is_private or ip.is_link_local) and not any(
        (ip.is_loopback, ip.is_multicast, ip.is_unspecified, ip.is_reserved)
    )


def resolve_local_host(host: str) -> tuple[str, tuple[str, ...]]:
    normalized = host.strip().rstrip(".")
    if not normalized or "/" in normalized or "://" in normalized:
        raise ValueError("host must be a local IP address or DNS name")
    try:
        addresses = tuple(
            sorted({item[4][0] for item in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)})
        )
    except socket.gaierror as exc:
        raise ValueError("host could not be resolved") from exc
    if not addresses or not all(_is_permitted_local_address(address) for address in addresses):
        raise ValueError("host must resolve only to private or link-local addresses")
    return normalized, addresses


def certified_profile(profile_id: str | None, model: str | None) -> dict[str, Any] | None:
    """Return externally provisioned qualification data; source ships no certifications."""
    if not profile_id or not model:
        return None
    try:
        profiles = json.loads(os.getenv("PIPHI_TP_LINK_CERTIFIED_PROFILES", "{}"))
    except json.JSONDecodeError:
        return None
    profile = profiles.get(profile_id) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict) or model not in profile.get("models", []):
        return None
    commands = profile.get("commands", [])
    if not isinstance(commands, list):
        return None
    return {"id": profile_id, "commands": [str(command) for command in commands]}
