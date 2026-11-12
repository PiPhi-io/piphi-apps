from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    market_area: str = Field(min_length=2, max_length=8)
    alias: str | None = None
    currency: Literal["EUR", "SEK", "NOK", "DKK", "GBP"] = "EUR"
    poll_interval_seconds: int = Field(default=3600, ge=900, le=86400)

    @field_validator("market_area")
    @classmethod
    def validate_market_area(cls, value: str) -> str:
        area = value.strip().upper()
        if not area or not all(char.isalnum() or char == "-" for char in area):
            raise ValueError("invalid market area")
        return area
