from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import schedule_telemetry_delivery

from .schemas import DeviceConfig
from .solaredge_client import MonitoringApiClient, SolarEdgeClient, SolarEdgeReading

LIVE_METRICS = (
    "production_power_w", "consumption_power_w", "grid_power_w",
    "battery_power_w", "battery_soc_percent",
)
SUMMARY_METRICS = (
    "today_energy_kwh", "month_energy_kwh", "year_energy_kwh",
    "lifetime_energy_kwh", "lifetime_revenue",
)
TELEMETRY_UNITS = {
    "production_power_w": "W", "consumption_power_w": "W", "grid_power_w": "W",
    "battery_power_w": "W", "battery_soc_percent": "%",
    "today_energy_kwh": "kWh", "month_energy_kwh": "kWh",
    "year_energy_kwh": "kWh", "lifetime_energy_kwh": "kWh",
    "lifetime_revenue": "currency",
}


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass(slots=True)
class ActiveSession:
    config: DeviceConfig
    client: SolarEdgeClient
    entry: dict[str, Any]
    credentials_key: tuple[int, str]
    last_summary_poll: float = 0.0
    last_summary_fingerprint: tuple[Any, ...] | None = None


class SolarEdgeRuntimeService:
    """Own one quota-conscious SolarEdge client and its freshness lifecycle."""

    def __init__(self, *, registry, runtime, telemetry, client_factory: Callable[[], SolarEdgeClient] = MonitoringApiClient):
        self.registry = registry
        self.runtime = runtime
        self.telemetry = telemetry
        self.client_factory = client_factory
        self._active: ActiveSession | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.poll_status: dict[str, dict[str, Any]] = {}

    @property
    def active_config_id(self) -> str | None:
        return str(self._active.entry["config_id"]) if self._active else None

    async def configure(self, config: DeviceConfig, entry: dict[str, Any]) -> None:
        async with self._lock:
            if self.active_config_id is not None and self.active_config_id != str(entry["config_id"]):
                raise HTTPException(status_code=409, detail={
                    "error": "instance_limit_reached",
                    "message": "This release supports one SolarEdge site per runtime.",
                    "maximum_instances": 1,
                })
            key = (config.site_id, config.secret_api_key())
            if self._active and self._active.credentials_key == key:
                self._active.config = config
                self._active.entry = entry
                return
            await self._stop_locked()
            client = self.client_factory()
            try:
                await client.authenticate(config)
                self._active = ActiveSession(config=config, client=client, entry=entry, credentials_key=key)
                await self._refresh_locked(force_summary=True)
            except Exception:
                await client.close()
                self._active = None
                raise
            self._poll_task = asyncio.create_task(self._poll_loop(), name="solaredge-poller")

    async def refresh(self, *, force_summary: bool = True) -> dict[str, Any]:
        async with self._lock:
            if self._active is None:
                raise HTTPException(status_code=409, detail="SolarEdge is not configured")
            return await self._refresh_locked(force_summary=force_summary)

    async def remove(self, config_id: str) -> bool:
        async with self._lock:
            if self.active_config_id != str(config_id):
                return False
            await self._stop_locked()
            self.poll_status.pop(str(config_id), None)
            return True

    async def close(self) -> None:
        async with self._lock:
            await self._stop_locked()

    def freshness_summary(self) -> dict[str, Any]:
        statuses = list(self.poll_status.values())
        return {
            "last_polled_at": _latest(statuses, "last_polled_at"),
            "last_sample_recorded_at": _latest(statuses, "last_sample_recorded_at"),
            "last_core_heartbeat_at": _latest(statuses, "last_core_heartbeat_at"),
            "read_failure_count": sum(int(item.get("read_failure_count", 0)) for item in statuses),
        }

    async def _stop_locked(self) -> None:
        task, self._poll_task = self._poll_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self._active is not None:
            await self._active.client.close()
        self._active = None

    async def _poll_loop(self) -> None:
        while self._active is not None:
            active = self._active
            await asyncio.sleep(active.config.poll_interval_seconds)
            try:
                async with self._lock:
                    if self._active is not active:
                        return
                    await self._refresh_locked(force_summary=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                # _refresh_locked records the failed read and Core heartbeat.
                continue

    def _record_read_failure(self, active: ActiveSession, exc: Exception) -> None:
        config_id = str(active.entry["config_id"])
        device_id = str(active.entry["device_id"])
        failed_at = _utc_now_iso()
        previous = self.registry.state_snapshots.get(config_id, {}).get("state", {})
        state = {**previous, "connected": False, "read_failed": True,
                 "last_error": str(exc), "last_polled_at": failed_at}
        self.registry.update_state(config_id, state, device_id=device_id)
        current = self.poll_status.get(config_id, {})
        self._update_poll_status(
            config_id, last_polled_at=failed_at, last_error=str(exc),
            read_failure_count=int(current.get("read_failure_count", 0)) + 1,
        )
        self._schedule_delivery(
            active, metrics={"connected": False, "read_failed": True}, units={},
            timestamp=failed_at, heartbeat=True,
        )

    async def _refresh_locked(self, *, force_summary: bool) -> dict[str, Any]:
        assert self._active is not None
        active = self._active
        now = monotonic()
        include_summary = force_summary or now - active.last_summary_poll >= active.config.summary_interval_seconds
        try:
            reading = await active.client.read(include_summary=include_summary)
        except Exception as exc:
            self._record_read_failure(active, exc)
            raise

        polled_at = _utc_now_iso()
        if include_summary:
            active.last_summary_poll = now
        config_id, device_id = str(active.entry["config_id"]), str(active.entry["device_id"])
        previous = self.registry.state_snapshots.get(config_id, {}).get("state", {})
        state = {**previous, **reading_to_state(reading, polled_at=polled_at), "summary_refreshed": include_summary}
        self.registry.update_state(config_id, state, device_id=device_id)
        self._update_poll_status(config_id, last_polled_at=polled_at, last_error=None)

        live = _present_metrics(state, LIVE_METRICS)
        self._schedule_delivery(
            active, metrics={"connected": True, "read_failed": False, **live},
            units=_units_for(live), timestamp=polled_at, heartbeat=True,
        )

        if include_summary:
            summary = _present_metrics(state, SUMMARY_METRICS)
            fingerprint = (reading.last_update, *(summary.get(key) for key in SUMMARY_METRICS))
            if summary and fingerprint != active.last_summary_fingerprint:
                active.last_summary_fingerprint = fingerprint
                self._schedule_delivery(
                    active, metrics=summary, units=_units_for(summary),
                    timestamp=polled_at, sample=True,
                )
                self._update_poll_status(config_id, last_sample_recorded_at=polled_at)
        return state

    def _schedule_delivery(
        self, active: ActiveSession, *, metrics: dict[str, Any], units: dict[str, str],
        timestamp: str, heartbeat: bool = False, sample: bool = False,
    ) -> None:
        config_id, device_id = str(active.entry["config_id"]), str(active.entry["device_id"])

        def on_failure(reason: Any, _context: dict[str, Any]) -> None:
            self._update_poll_status(config_id, last_core_delivery_error=str(reason))

        task = schedule_telemetry_delivery(
            process_state=self.runtime.process_state, telemetry_client=self.telemetry,
            auth_context=self.runtime.auth, config_id=config_id, device_id=device_id,
            container_id=active.entry.get("container_id"), metrics=metrics, units=units,
            timestamp=timestamp, on_skipped=on_failure, on_error=on_failure,
        )
        if hasattr(task, "add_done_callback"):
            def completed(future: asyncio.Future[bool]) -> None:
                try:
                    delivered = future.result()
                except Exception as exc:  # pragma: no cover - SDK reports through on_error
                    on_failure(exc, {})
                    return
                if not delivered:
                    return
                updates: dict[str, Any] = {"last_core_delivery_error": None}
                if heartbeat:
                    updates["last_core_heartbeat_at"] = timestamp
                if sample:
                    updates["last_sample_delivered_at"] = timestamp
                self._update_poll_status(config_id, **updates)

            task.add_done_callback(completed)

    def _update_poll_status(self, config_id: str, **updates: Any) -> None:
        self.poll_status[config_id] = {**self.poll_status.get(config_id, {}), **updates}


def _present_metrics(state: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: state[name] for name in names if isinstance(state.get(name), (bool, int, float))}


def _units_for(metrics: dict[str, Any]) -> dict[str, str]:
    return {name: TELEMETRY_UNITS[name] for name in metrics if name in TELEMETRY_UNITS}


def _latest(statuses: list[dict[str, Any]], key: str) -> str | None:
    values = sorted(str(status[key]) for status in statuses if status.get(key))
    return values[-1] if values else None


def reading_to_state(reading: SolarEdgeReading, *, polled_at: str | None = None) -> dict[str, Any]:
    return {
        "connected": True, "read_failed": False, "last_error": None,
        "last_polled_at": polled_at or _utc_now_iso(), "vendor_last_update": reading.last_update,
        "site_id": reading.site_id, "site_name": reading.site_name, "site_status": reading.site_status,
        "production_power_w": reading.production_power_w,
        "consumption_power_w": reading.consumption_power_w, "grid_power_w": reading.grid_power_w,
        "battery_power_w": reading.battery_power_w, "battery_soc_percent": reading.battery_soc_percent,
        "today_energy_kwh": reading.today_energy_kwh, "month_energy_kwh": reading.month_energy_kwh,
        "year_energy_kwh": reading.year_energy_kwh, "lifetime_energy_kwh": reading.lifetime_energy_kwh,
        "lifetime_revenue": reading.lifetime_revenue,
    }
