from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr, field_validator


class WyzeBridgeConfig(BaseModel):
    wyze_email: str = Field(min_length=3, max_length=320)
    wyze_password: SecretStr = Field(min_length=1, max_length=512)
    api_id: SecretStr = Field(min_length=1, max_length=512)
    api_key: SecretStr = Field(min_length=1, max_length=1024)
    advertised_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    enabled_camera_names: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("wyze_email", "advertised_host")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char in normalized for char in "\r\n\0"):
            raise ValueError("value must be non-empty and contain no control characters")
        return normalized

    @field_validator("enabled_camera_names")
    @classmethod
    def normalize_camera_names(cls, value: list[str]) -> list[str]:
        normalized = []
        for item in value:
            name = str(item or "").strip()
            if not name or any(char in name for char in "\r\n\0"):
                raise ValueError("camera names must be non-empty and contain no control characters")
            if name not in normalized:
                normalized.append(name)
        return normalized
