from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import schedule_telemetry_delivery

from .schemas import DeviceConfig
from .sense_client import SenseClient, SenseEnergyClient, SenseReading


@dataclass(slots=True)
class ActiveSenseSession:
    config: DeviceConfig
    client: SenseClient
    entry: dict[str, Any]
    credentials_key: tuple[str, str]
    last_trend_poll: float = 0.0


class SenseRuntimeService:
    """Own exactly one reusable Sense client and its polling task."""

    def __init__(self, *, registry, runtime, telemetry, client_factory: Callable[[], SenseClient] = SenseEnergyClient):
        self.registry = registry
        self.runtime = runtime
        self.telemetry = telemetry
        self.client_factory = client_factory
        self._active: ActiveSenseSession | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def active_config_id(self) -> str | None:
        return str(self._active.entry["config_id"]) if self._active else None

    async def configure(self, config: DeviceConfig, entry: dict[str, Any]) -> None:
        async with self._lock:
            active_id = self.active_config_id
            config_id = str(entry["config_id"])
            if active_id is not None and active_id != config_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "instance_limit_reached",
                        "message": "Sense supports one configured account per PiPhi Core installation.",
                        "maximum_instances": 1,
                    },
                )

            credentials_key = (config.email, config.secret_password())
            if self._active and self._active.credentials_key == credentials_key:
                self._active.config = config
                self._active.entry = entry
                return

            await self._stop_locked()
            client = self.client_factory()
            try:
                await client.authenticate(config)
            except Exception:
                await client.close()
                raise
            self._active = ActiveSenseSession(
                config=config,
                client=client,
                entry=entry,
                credentials_key=credentials_key,
            )
            try:
                await self._refresh_locked(force_trends=True)
            except Exception:
                await self._stop_locked()
                raise
            self._poll_task = asyncio.create_task(self._poll_loop(), name="sense-energy-poller")

    async def refresh(self, *, force_trends: bool = False) -> dict[str, Any]:
        async with self._lock:
            if self._active is None:
                raise HTTPException(status_code=409, detail="Sense is not configured")
            return await self._refresh_locked(force_trends=force_trends)

    async def remove(self, config_id: str) -> bool:
        async with self._lock:
            if self.active_config_id != str(config_id):
                return False
            await self._stop_locked()
            return True

    async def close(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        task = self._poll_task
        self._poll_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self._active is not None:
            await self._active.client.close()
        self._active = None

    async def _poll_loop(self) -> None:
        while True:
            active = self._active
            if active is None:
                return
            await asyncio.sleep(active.config.poll_interval_seconds)
            try:
                async with self._lock:
                    if self._active is not active:
                        return
                    await self._refresh_locked(force_trends=False)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep the long-lived session alive after transient API failures
                self.registry.update_state(
                    str(active.entry["config_id"]),
                    {"connected": False, "error": str(exc)},
                    device_id=str(active.entry["device_id"]),
                )

    async def _refresh_locked(self, *, force_trends: bool) -> dict[str, Any]:
        assert self._active is not None
        active = self._active
        now = monotonic()
        include_trends = force_trends or now - active.last_trend_poll >= active.config.trend_interval_seconds
        reading = await active.client.read(include_trends=include_trends)
        if include_trends:
            active.last_trend_poll = now
        state = _reading_to_state(reading)
        config_id = str(active.entry["config_id"])
        device_id = str(active.entry["device_id"])
        self.registry.update_state(config_id, state, device_id=device_id)
        schedule_telemetry_delivery(
            process_state=self.runtime.process_state,
            telemetry_client=self.telemetry,
            auth_context=self.runtime.auth,
            config_id=config_id,
            device_id=device_id,
            container_id=active.entry.get("container_id"),
            metrics={key: value for key, value in state.items() if isinstance(value, (bool, int, float))},
            units=TELEMETRY_UNITS,
        )
        for device in reading.devices:
            schedule_telemetry_delivery(
                process_state=self.runtime.process_state,
                telemetry_client=self.telemetry,
                auth_context=self.runtime.auth,
                config_id=config_id,
                device_id=device.device_id,
                container_id=active.entry.get("container_id"),
                metrics={
                    "device_power_w": device.power_w,
                    "device_on": device.is_on,
                    "device_daily_energy_kwh": device.daily_energy_kwh,
                },
                units=DEVICE_TELEMETRY_UNITS,
            )
        return state


TELEMETRY_UNITS = {
    "active_power_w": "W",
    "active_solar_power_w": "W",
    "voltage_l1_v": "V",
    "voltage_l2_v": "V",
    "frequency_hz": "Hz",
    "daily_usage_kwh": "kWh",
    "daily_production_kwh": "kWh",
    "daily_from_grid_kwh": "kWh",
    "daily_to_grid_kwh": "kWh",
    "always_on_power_w": "W",
    "other_power_w": "W",
}

DEVICE_TELEMETRY_UNITS = {
    "device_power_w": "W",
    "device_on": "bool",
    "device_daily_energy_kwh": "kWh",
}


def _reading_to_state(reading: SenseReading) -> dict[str, Any]:
    state: dict[str, Any] = {
        "connected": True,
        "monitor_id": reading.monitor_id,
        "time_zone": reading.time_zone,
        "active_power_w": reading.active_power_w,
        "active_solar_power_w": reading.active_solar_power_w,
        "frequency_hz": reading.frequency_hz,
        "daily_usage_kwh": reading.daily_usage_kwh,
        "daily_production_kwh": reading.daily_production_kwh,
        "daily_from_grid_kwh": reading.daily_from_grid_kwh,
        "daily_to_grid_kwh": reading.daily_to_grid_kwh,
        "active_device_count": sum(1 for device in reading.devices if device.is_on),
        "always_on_power_w": reading.always_on_power_w,
        "other_power_w": reading.other_power_w,
        "devices": [
            {
                "device_id": device.device_id,
                "name": device.name,
                "icon": device.icon,
                "power_w": device.power_w,
                "is_on": device.is_on,
                "daily_energy_kwh": device.daily_energy_kwh,
                "device_type": device.device_type,
                "first_usage": device.first_usage,
                "timeline_enabled": device.timeline_enabled,
            }
            for device in reading.devices
        ],
        "timeline_events": [
            {
                "event_id": event.event_id,
                "occurred_at": event.occurred_at,
                "event_type": event.event_type,
                "subtype": event.subtype,
                "body": event.body,
                "device_id": event.device_id,
                "device_name": event.device_name,
                "icon": event.icon,
            }
            for event in reading.timeline_events
        ],
    }
    if reading.voltage_v:
        state["voltage_l1_v"] = reading.voltage_v[0]
    if len(reading.voltage_v) > 1:
        state["voltage_l2_v"] = reading.voltage_v[1]
    return state
