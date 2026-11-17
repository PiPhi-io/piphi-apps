from __future__ import annotations

from pathlib import PurePosixPath

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, SecretStr, model_validator


class DeviceConfig(RuntimeConfig):
    host: str
    alias: str | None = None
    password: SecretStr | None = None
    api_key: SecretStr | None = Field(default=None, exclude=True)
    base_url: str | None = None
    poll_interval_seconds: int = Field(default=300, ge=60, le=3600)
    service_name: str | None = None
    username: str | None = None
    ca_bundle_path: str | None = None

    @model_validator(mode="after")
    def migrate_legacy_password(self) -> DeviceConfig:
        if self.password is None and self.api_key is not None:
            self.password = self.api_key
        if not self.username or self.password is None or not self.secret_password():
            raise ValueError("RouterOS username and password are required")
        if self.ca_bundle_path and not _approved_ca_path(self.ca_bundle_path):
            raise ValueError(
                "ca_bundle_path must use an approved read-only certificate mount"
            )
        return self

    def secret_password(self) -> str:
        return self.password.get_secret_value() if self.password else ""


def _approved_ca_path(value: str) -> bool:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        return False
    return any(
        path != root and path.is_relative_to(root)
        for root in (PurePosixPath("/etc/ssl/certs"), PurePosixPath("/run/secrets"))
    )
