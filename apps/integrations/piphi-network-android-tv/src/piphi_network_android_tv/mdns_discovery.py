from __future__ import annotations

import asyncio
import ipaddress
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

ANDROID_TV_REMOTE_V2_SERVICE = "_androidtvremote2._tcp.local."
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 3.0
MAX_DISCOVERY_TIMEOUT_SECONDS = 10.0

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MdnsService:
    """One service record returned by an mDNS backend."""

    service_type: Any
    name: Any
    host: Any
    port: Any


class DiscoveryBackend(Protocol):
    """Injectable network boundary used by :class:`RemoteV2MdnsDiscovery`."""

    async def browse(
        self, service_type: str
    ) -> Iterable[MdnsService | Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class UnverifiedRemoteV2Candidate:
    """An endpoint hint that must not be used as a device identity.

    Android TV Remote v2 only reveals MAC-backed identity after authenticated
    TLS/pairing. Consequently, discovery cannot provide a stable device ID.
    """

    name: str
    host: str
    port: int
    service_type: str = field(init=False, default=ANDROID_TV_REMOTE_V2_SERVICE)
    verification_status: str = field(init=False, default="unverified")
    stable_device_id: None = field(init=False, default=None)


class RemoteV2MdnsDiscovery:
    """Discover and sanitize unverified Android TV Remote v2 candidates."""

    def __init__(
        self,
        backend: DiscoveryBackend,
        *,
        timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise TypeError("timeout_seconds must be a number")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero")
        self._backend = backend
        self._timeout_seconds = min(float(timeout_seconds), MAX_DISCOVERY_TIMEOUT_SECONDS)

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def discover(self) -> tuple[UnverifiedRemoteV2Candidate, ...]:
        """Return normalized candidates, or no candidates when browsing times out."""

        try:
            records = await asyncio.wait_for(
                self._backend.browse(ANDROID_TV_REMOTE_V2_SERVICE),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return ()

        candidates: dict[tuple[str, str, int], UnverifiedRemoteV2Candidate] = {}
        for record in records:
            candidate = _candidate_from_record(record)
            if candidate is None:
                continue
            # This key only coalesces duplicate announcements. It is deliberately
            # not exposed or persisted as a device identity.
            key = (candidate.name.casefold(), candidate.host, candidate.port)
            previous = candidates.get(key)
            if previous is None or candidate.name < previous.name:
                candidates[key] = candidate

        return tuple(
            sorted(
                candidates.values(),
                key=lambda item: (item.name.casefold(), item.host, item.port, item.name),
            )
        )


def _candidate_from_record(
    record: MdnsService | Mapping[str, Any],
) -> UnverifiedRemoteV2Candidate | None:
    try:
        if isinstance(record, Mapping):
            service_type = record["service_type"]
            name = record["name"]
            host = record["host"]
            port = record["port"]
        else:
            service_type = record.service_type
            name = record.name
            host = record.host
            port = record.port

        if _normalize_service_type(service_type) != ANDROID_TV_REMOTE_V2_SERVICE:
            return None
        return UnverifiedRemoteV2Candidate(
            name=_normalize_name(name),
            host=_normalize_host(host),
            port=_normalize_port(port),
        )
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        return None


def _normalize_service_type(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("service type must be text")
    normalized = value.strip().lower().rstrip(".") + "."
    return normalized


def _normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("service name must be text")
    name = unicodedata.normalize("NFC", value).strip()
    suffix = "." + ANDROID_TV_REMOTE_V2_SERVICE
    if name.casefold().endswith(suffix.casefold()):
        name = name[: -len(suffix)].strip()
    name = " ".join(name.split())
    if not name or any(unicodedata.category(character) == "Cc" for character in name):
        raise ValueError("service name is empty or contains control characters")
    return name


def _normalize_host(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("host must be text")
    host = value.strip().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or any(character.isspace() for character in host):
        raise ValueError("host is empty or contains whitespace")

    try:
        return ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        pass

    ascii_host = host.encode("idna").decode("ascii").lower()
    if len(ascii_host) > 253:
        raise ValueError("host is too long")
    labels = ascii_host.split(".")
    if any(not _DNS_LABEL.fullmatch(label) for label in labels):
        raise ValueError("host is not a valid DNS name")
    return ascii_host


def _normalize_port(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("port must be an integer")
    if isinstance(value, str):
        if not value.strip().isdecimal():
            raise ValueError("port must be an integer")
        port = int(value.strip())
    elif isinstance(value, int):
        port = value
    else:
        raise TypeError("port must be an integer")
    if not 1 <= port <= 65535:
        raise ValueError("port is outside the TCP port range")
    return port
