from __future__ import annotations

from dataclasses import replace

from .extended_api import SenseTimelineEvent
from .sense_client import SenseDeviceReading, SenseReading

QUALIFICATION_SCENARIO = "release-qualification-v1"


class DeterministicFakeSenseClient:
    """Network-free account fixture used only by release qualification."""

    monitor_id = "qualification-monitor-01"

    def __init__(self) -> None:
        self._closed = False
        self._reads = 0

    async def authenticate(self, config) -> None:
        if config.email != "fixture@example.invalid" or config.secret_password() != "fixture-password":
            from .sense_client import SenseAuthenticationError

            raise SenseAuthenticationError("The deterministic Sense fixture rejected the credentials.")

    async def read(self, *, include_trends: bool) -> SenseReading:
        if self._closed:
            raise RuntimeError("fake Sense client is closed")
        self._reads += 1
        reading = SenseReading(
            monitor_id=self.monitor_id,
            time_zone="America/New_York",
            active_power_w=842.5,
            active_solar_power_w=250.0,
            voltage_v=(121.1, 120.8),
            frequency_hz=60.0,
            daily_usage_kwh=8.4,
            daily_production_kwh=3.2,
            daily_from_grid_kwh=5.5,
            daily_to_grid_kwh=0.3,
            devices=(
                SenseDeviceReading(
                    "fixture-appliance-01",
                    "Qualification refrigerator",
                    "fridge",
                    112.0,
                    True,
                    1.4,
                    device_type="Refrigerator",
                    first_usage="2026-01-01",
                    timeline_enabled=True,
                ),
            ),
            always_on_power_w=125.0,
            other_power_w=75.0,
            timeline_events=(
                SenseTimelineEvent(
                    "fixture-event-01",
                    "2026-01-01T12:00:00Z",
                    "DeviceOn",
                    "Qualification appliance turned on",
                    device_id="fixture-appliance-01",
                    device_name="Qualification refrigerator",
                    icon="fridge",
                ),
            ),
        )
        # Realtime changes deterministically while daily period values remain stable.
        return replace(reading, active_power_w=reading.active_power_w + self._reads - 1)

    async def close(self) -> None:
        self._closed = True
