from __future__ import annotations

from pydantic import Field, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    network_id: str = "managed"
    expected_controller_identity_hash: str | None = None
    alias: str | None = None
    event_poll_interval_seconds: float = Field(default=1.0, ge=0.25, le=30.0)

    @field_validator("alias")
    @classmethod
    def normalize_alias(cls, value: str | None) -> str | None:
        token = str(value or "").strip()
        return token or None

    @field_validator("network_id")
    @classmethod
    def validate_network_id(cls, value: str) -> str:
        token = str(value or "").strip().lower()
        if token != "managed":
            raise ValueError("only the managed Z-Wave network is supported")
        return token

    @field_validator("expected_controller_identity_hash")
    @classmethod
    def validate_controller_hash(cls, value: str | None) -> str | None:
        token = str(value or "").strip().lower()
        if token and (len(token) != 64 or any(char not in "0123456789abcdef" for char in token)):
            raise ValueError("expected_controller_identity_hash must be a SHA-256 digest")
        return token or None
