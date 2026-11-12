from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, SecretStr, field_validator, model_validator


class DeviceConfig(RuntimeConfig):
    source_url: SecretStr
    username: str | None = Field(default=None, max_length=512)
    password: SecretStr | None = Field(default=None, max_length=1024)
    alias: str | None = Field(default=None, max_length=120)
    preferred_transport: str = Field(default="tcp", pattern="^(tcp|udp|auto)$")

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: SecretStr) -> SecretStr:
        source = value.get_secret_value().strip()
        parsed = urlsplit(source)
        if len(source) > 4096 or any(character in source for character in "\r\n\0") or parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
            raise ValueError("source_url must be a valid RTSP or RTSPS camera URL")
        if parsed.username is not None and parsed.password is None:
            raise ValueError(
                "source_url credentials must use username:password@camera-host"
            )
        return SecretStr(source)

    @model_validator(mode="after")
    def validate_credentials(self) -> DeviceConfig:
        username = str(self.username or "").strip()
        password = self.password.get_secret_value() if self.password is not None else ""
        if bool(username) != bool(password):
            raise ValueError("Provide the camera username and password together")

        parsed = urlsplit(self.source_url.get_secret_value())
        if username and (parsed.username is not None or parsed.password is not None):
            raise ValueError(
                "Provide camera credentials either separate fields or the URL, not both"
            )
        self.username = username or None
        return self

    def authenticated_source_url(self) -> SecretStr:
        source = self.source_url.get_secret_value()
        if self.username is None or self.password is None:
            return SecretStr(source)

        parsed = urlsplit(source)
        hostname = str(parsed.hostname or "")
        rendered_host = f"[{hostname}]" if ":" in hostname else hostname
        port = f":{parsed.port}" if parsed.port is not None else ""
        username = quote(self.username, safe="")
        password = quote(self.password.get_secret_value(), safe="")
        netloc = f"{username}:{password}@{rendered_host}{port}"
        return SecretStr(
            urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        )
