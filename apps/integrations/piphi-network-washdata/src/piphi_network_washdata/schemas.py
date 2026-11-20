from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, model_validator


class DeviceConfig(RuntimeConfig):
    """One threshold-based monitor backed by a Core source binding."""

    alias: str = Field(default="Appliance cycle", min_length=1, max_length=100)
    binding_key: str = Field(default="appliance_power", min_length=1, max_length=100)
    power_metric: str = Field(default="power_w", min_length=1, max_length=100)
    start_threshold_w: float = Field(default=10.0, ge=0, le=100_000)
    stop_threshold_w: float = Field(default=5.0, ge=0, le=100_000)
    start_debounce_samples: int = Field(default=2, ge=1, le=100)
    stop_debounce_samples: int = Field(default=3, ge=1, le=100)
    poll_interval_seconds: float = Field(default=5.0, ge=1, le=300)
    page_size: int = Field(default=100, ge=1, le=500)
    max_sample_gap_seconds: int = Field(default=900, ge=1, le=86_400)

    @model_validator(mode="after")
    def validate_thresholds(self) -> DeviceConfig:
        if self.stop_threshold_w > self.start_threshold_w:
            raise ValueError("stop_threshold_w cannot exceed start_threshold_w")
        return self
