from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    email: str
    password: SecretStr
    alias: str | None = "Sense Home"
    mfa_code: SecretStr | None = None
    poll_interval_seconds: int = Field(default=60, ge=60, le=3600)
    trend_interval_seconds: int = Field(default=900, ge=300, le=86400)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("email must be a valid Sense account email")
        return normalized

    def secret_password(self) -> str:
        return self.password.get_secret_value()

    def secret_mfa_code(self) -> str | None:
        return self.mfa_code.get_secret_value() if self.mfa_code else None
