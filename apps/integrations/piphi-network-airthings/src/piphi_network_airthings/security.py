from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr

from .cloud.client import AirthingsCredentials


REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "account_id",
    "access_token",
    "authorization",
    "client_id",
    "credential",
    "device_name",
    "home",
    "location",
    "raw",
    "secret",
    "segment",
    "serial",
    "token",
)


def _sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_sensitive(value: Any, *, secrets: Sequence[str] = ()) -> Any:
    """Return a recursive, non-mutating privacy-safe projection."""
    secret_values = tuple(secret for secret in secrets if secret)
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED
                if _sensitive_key(key)
                else redact_sensitive(item, secrets=secret_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_sensitive(item, secrets=secret_values) for item in value]
    if isinstance(value, str):
        sanitized = value
        for secret in secret_values:
            sanitized = sanitized.replace(secret, REDACTED)
        return sanitized
    return value


@dataclass(slots=True, repr=False)
class StoredAirthingsSecrets:
    client_id: SecretStr
    client_secret: SecretStr
    account_id: SecretStr
    serial_number: SecretStr

    def credentials(self) -> AirthingsCredentials:
        return AirthingsCredentials(
            client_id=self.client_id.get_secret_value(),
            client_secret=self.client_secret.get_secret_value(),
        )


@dataclass(slots=True, repr=False)
class RuntimeSecretStore:
    _entries: dict[str, StoredAirthingsSecrets] = field(default_factory=dict, repr=False)

    def set(self, config_id: str, secrets: StoredAirthingsSecrets) -> None:
        self._entries[config_id] = secrets

    def get(self, config_id: str) -> StoredAirthingsSecrets | None:
        return self._entries.get(config_id)

    def remove(self, config_id: str) -> None:
        self._entries.pop(config_id, None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
