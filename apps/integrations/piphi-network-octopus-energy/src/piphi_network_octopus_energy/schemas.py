from __future__ import annotations

from typing import Any

from pydantic import model_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str = "api.octopus.energy"
    alias: str | None = None
    poll_interval_seconds: int | None = None
    service_name: str | None = None
    product_code: str | None = None
    tariff_code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_account_credentials(cls, value: Any) -> Any:
        if isinstance(value, dict):
            forbidden = {
                "api_key",
                "access_token",
                "account_id",
                "base_url",
                "client_secret",
                "meter_mpan",
                "password",
                "refresh_token",
            }
            supplied = sorted(forbidden.intersection(value))
            if supplied:
                raise ValueError(
                    "Octopus public tariff configuration does not accept account "
                    f"credentials or endpoint overrides: {', '.join(supplied)}"
                )
        return value
