from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


KNOWN_AQARA_REGIONS = {
    "cn": "China mainland",
    "us": "United States",
    "eu": "Europe",
    "kr": "South Korea",
    "ru": "Russia",
    "sg": "Singapore",
}


@dataclass(slots=True)
class AqaraAuthTokens:
    access_token: str
    open_id: str
    refresh_token: str | None = None
    expires_in: int | None = None


@dataclass(slots=True)
class AqaraCloudCredentials:
    region: str
    app_id: str
    key_id: str
    app_key: str
    access_token: str = ""
    open_id: str = ""
    refresh_token: str | None = None
    account: str | None = None
    account_type: int = 0
    custom_api_domain: str | None = None
    lang: str = "en"

    def cache_key(self) -> str:
        account_key = self.open_id or self.account or self.access_token or "anonymous"
        return f"{self.region}:{self.app_id}:{self.key_id}:{account_key}"

    def with_tokens(self, tokens: AqaraAuthTokens) -> "AqaraCloudCredentials":
        return AqaraCloudCredentials(
            region=self.region,
            app_id=self.app_id,
            key_id=self.key_id,
            app_key=self.app_key,
            access_token=tokens.access_token,
            open_id=tokens.open_id,
            refresh_token=tokens.refresh_token,
            account=self.account,
            account_type=self.account_type,
            custom_api_domain=self.custom_api_domain,
            lang=self.lang,
        )


@dataclass(slots=True)
class AqaraResourceInfo:
    resource_id: str
    name: str
    description: str | None = None
    access: int | None = None
    unit: int | None = None
    enums: str | None = None
    default_value: str | None = None
    min_value: int | None = None
    max_value: int | None = None
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_readable(self) -> bool:
        return int(self.access or 0) in {1, 3, 5, 7}

    @property
    def is_writable(self) -> bool:
        return int(self.access or 0) in {4, 5, 6, 7}


@dataclass(slots=True)
class AqaraResourceValue:
    subject_id: str
    resource_id: str
    value: str
    timestamp_ms: int | None = None

    @property
    def recorded_at(self) -> str:
        if self.timestamp_ms is None:
            return datetime.now(tz=UTC).isoformat()
        return datetime.fromtimestamp(self.timestamp_ms / 1000.0, tz=UTC).isoformat()


@dataclass(slots=True)
class AqaraCloudDevice:
    did: str
    name: str
    model: str
    parent_did: str | None = None
    position_id: str | None = None
    model_type: int | None = None
    state: int | None = None
    firmware_version: str | None = None
    time_zone: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def model_name(self) -> str:
        return self.model or "Aqara Device"

    def to_discovery_record(
        self,
        *,
        credentials: AqaraCloudCredentials,
    ) -> dict[str, Any]:
        return {
            "id": self.did,
            "did": self.did,
            "device_id": self.did,
            "name": self.name or self.did,
            "device_model": self.model,
            "model": self.model,
            "region": credentials.region,
            "app_id": credentials.app_id,
            "key_id": credentials.key_id,
            "app_key": credentials.app_key,
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
            "open_id": credentials.open_id,
            "custom_api_domain": credentials.custom_api_domain,
            "account": credentials.account,
            "account_type": credentials.account_type,
            "metadata": {
                "did": self.did,
                "model": self.model,
                "parent_did": self.parent_did,
                "position_id": self.position_id,
                "model_type": self.model_type,
                "state": self.state,
                "firmware_version": self.firmware_version,
                "time_zone": self.time_zone,
            },
        }
