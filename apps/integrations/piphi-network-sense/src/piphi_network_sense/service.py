from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from piphi_runtime_kit_python import schedule_telemetry_delivery

from .schemas import DeviceConfig
from .sense_client import (
    SenseAuthenticationError,
    SenseClient,
    SenseEnergyClient,
    SenseRateLimitError,
    SenseReading,
)


@dataclass(slots=True)
class ActiveSenseSession:
    config: DeviceConfig
    client: SenseClient
    entry: dict[str, Any]
    credentials_key: str
    last_trend_poll: float = 0.0
    failure_count: int = 0
    retry_after_seconds: float | None = None
    realtime_observed_at: datetime | None = None
    trends_observed_at: datetime | None = None
    private_observed_at: datetime | None = None


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

            credentials_key = sha256(
                f"{config.email}\0{config.secret_password()}".encode()
            ).hexdigest()
            if self._active and self._active.credentials_key == credentials_key:
                self._active.config = config
                entry["device_id"] = str(self._active.client.monitor_id)
                self._active.entry = entry
                return

            previous = self._active
            client = self.client_factory()
            try:
                await client.authenticate(config)
                if previous is not None and str(client.monitor_id) != str(previous.client.monitor_id):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "account_identity_changed",
                            "message": "Reconfiguration resolved to a different Sense monitor; remove the existing configuration first.",
                        },
                    )
                candidate = ActiveSenseSession(
                    config=config,
                    client=client,
                    entry=entry,
                    credentials_key=credentials_key,
                )
                entry["device_id"] = str(client.monitor_id)
                reading = await client.read(include_trends=True)
            except Exception:
                await client.close()
                raise
            old_task, self._poll_task = self._poll_task, None
            self._active = candidate
            try:
                self._record_reading(candidate, reading, include_trends=True)
            except Exception:
                self._active = previous
                self._poll_task = old_task
                await client.close()
                raise
            if old_task is not None and old_task is not asyncio.current_task():
                old_task.cancel()
                with suppress(asyncio.CancelledError):
                    await old_task
            if previous is not None:
                await previous.client.close()
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
            backoff = active.config.poll_interval_seconds * (2 ** min(active.failure_count, 5))
            delay = active.retry_after_seconds or backoff
            await asyncio.sleep(min(max(delay, active.config.poll_interval_seconds), 1800))
            try:
                async with self._lock:
                    if self._active is not active:
                        return
                    await self._refresh_locked(force_trends=False)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep transient recovery bounded and observable
                if isinstance(exc, SenseAuthenticationError):
                    return

    async def _refresh_locked(self, *, force_trends: bool) -> dict[str, Any]:
        assert self._active is not None
        active = self._active
        now = monotonic()
        include_trends = force_trends or now - active.last_trend_poll >= active.config.trend_interval_seconds
        try:
            reading = await active.client.read(include_trends=include_trends)
        except Exception as exc:
            self._record_failure(active, exc)
            raise
        active.failure_count = 0
        active.retry_after_seconds = None
        if include_trends:
            active.last_trend_poll = now
        return self._record_reading(active, reading, include_trends=include_trends)

    def _record_failure(self, active: ActiveSenseSession, exc: Exception) -> None:
        active.failure_count = min(active.failure_count + 1, 6)
        active.retry_after_seconds = (
            exc.retry_after_seconds if isinstance(exc, SenseRateLimitError) else None
        )
        config_id = str(active.entry["config_id"])
        previous = (
            self.registry.state_snapshots.get(config_id, {}).get("state", {})
            if hasattr(self.registry, "state_snapshots")
            else {}
        )
        failed_at = datetime.now(tz=UTC)
        freshness = _freshness_payload(
            active,
            now=failed_at,
            realtime_failed=True,
        )
        self.registry.update_state(
            config_id,
            {
                **previous,
                "connected": False,
                "available": False,
                "stale": True,
                "freshness": freshness,
                "error_class": _error_class(exc),
                "reauth_required": isinstance(exc, SenseAuthenticationError),
                "last_poll_failed_at": failed_at.isoformat(),
                "retry": {
                    "attempt": active.failure_count,
                    "maximum_backoff_seconds": 1800,
                    "retry_after_seconds": active.retry_after_seconds,
                    "blocked_until_reconfigure": isinstance(exc, SenseAuthenticationError),
                },
            },
            device_id=str(active.entry["device_id"]),
        )

    def _record_reading(
        self,
        active: ActiveSenseSession,
        reading: SenseReading,
        *,
        include_trends: bool,
    ) -> dict[str, Any]:
        observed_at = datetime.now(tz=UTC)
        active.realtime_observed_at = observed_at
        if include_trends:
            active.trends_observed_at = observed_at
            active.private_observed_at = observed_at
        state = _reading_to_state(
            reading,
            expose_appliance_activity=active.config.expose_appliance_activity,
            expose_timeline=active.config.expose_timeline,
            fetched_at=observed_at,
        )
        state["freshness"] = _freshness_payload(active, now=observed_at)
        state["periods"] = _daily_period(reading.time_zone, observed_at)
        state["retry"] = {
            "attempt": 0,
            "maximum_backoff_seconds": 1800,
            "retry_after_seconds": None,
            "blocked_until_reconfigure": False,
        }
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
        for device in reading.devices if active.config.expose_appliance_activity else ():
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


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _error_class(exc: Exception) -> str:
    if isinstance(exc, SenseAuthenticationError):
        return "authentication"
    if isinstance(exc, SenseRateLimitError):
        return "rate_limit"
    return "transient_outage"


def _reading_to_state(
    reading: SenseReading,
    *,
    expose_appliance_activity: bool = False,
    expose_timeline: bool = False,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    fetched_at_text = (fetched_at or datetime.now(tz=UTC)).isoformat()
    state: dict[str, Any] = {
        "connected": True,
        "available": True,
        "stale": False,
        "fetched_at": fetched_at_text,
        "last_success_at": fetched_at_text,
        "error_class": None,
        "reauth_required": False,
        "monitor_id": reading.monitor_id,
        "time_zone": reading.time_zone,
        "active_power_w": reading.active_power_w,
        "active_solar_power_w": reading.active_solar_power_w,
        "frequency_hz": reading.frequency_hz,
        "daily_usage_kwh": reading.daily_usage_kwh,
        "daily_production_kwh": reading.daily_production_kwh,
        "daily_from_grid_kwh": reading.daily_from_grid_kwh,
        "daily_to_grid_kwh": reading.daily_to_grid_kwh,
        "active_device_count": (
            sum(1 for device in reading.devices if device.is_on)
            if expose_appliance_activity else None
        ),
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
            if expose_appliance_activity
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
            for event in reading.timeline_events[:20]
            if expose_timeline
        ],
    }
    if reading.voltage_v:
        state["voltage_l1_v"] = reading.voltage_v[0]
    if len(reading.voltage_v) > 1:
        state["voltage_l2_v"] = reading.voltage_v[1]
    return state


def _freshness_payload(
    active: ActiveSenseSession,
    *,
    now: datetime,
    realtime_failed: bool = False,
) -> dict[str, dict[str, Any]]:
    def status(observed: datetime | None, max_age: int, *, force_stale: bool = False):
        age = None if observed is None else max(0, int((now - observed).total_seconds()))
        return {
            "observed_at": observed.isoformat() if observed else None,
            "age_seconds": age,
            "max_age_seconds": max_age,
            "stale": force_stale or age is None or age > max_age,
        }

    return {
        "realtime": status(
            active.realtime_observed_at,
            max(active.config.poll_interval_seconds * 2, 120),
            force_stale=realtime_failed,
        ),
        "daily_trends": status(
            active.trends_observed_at,
            max(active.config.trend_interval_seconds * 2, 1800),
        ),
        "private_activity": status(
            active.private_observed_at,
            max(active.config.trend_interval_seconds * 2, 1800),
        ),
    }


def _daily_period(time_zone: str, observed_at: datetime) -> dict[str, Any]:
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
        time_zone = "UTC"
    local = observed_at.astimezone(zone)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "daily": {
            "kind": "provider_local_calendar_day",
            "time_zone": time_zone,
            "start": start.isoformat(),
            "end_exclusive": (start + timedelta(days=1)).isoformat(),
            "complete": False,
        }
    }
