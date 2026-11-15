from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .gateway import BleGatewayClient, CursorGap, GatewayError, Observation
from .inference import DeviceState, PresenceEngine, Receiver
from .schemas import DeviceConfig


def entity_id(config_id: str, handle: str) -> str:
    return f"{config_id}:ble:{hashlib.sha256(handle.encode()).hexdigest()[:16]}"


class PresenceCoordinator:
    def __init__(self, config: DeviceConfig, transition: Callable[[str, DeviceState], None], client: BleGatewayClient | None = None):
        self.config = config
        self.client = client
        self.cursor = 0
        self.last_error: str | None = None
        self.gateway_available = False
        self._poll_count = 0
        self.task: asyncio.Task[None] | None = None
        self.engine = PresenceEngine(
            config.selected_device_handles,
            consider_home_seconds=config.consider_home_seconds,
            stale_seconds=config.stale_seconds,
            reference_power_dbm=config.reference_power_dbm,
            attenuation_factor=config.attenuation_factor,
            smoothing_samples=config.smoothing_samples,
            switch_margin_m=config.area_switch_margin_m,
            switch_samples=config.area_switch_samples,
            max_velocity_m_s=config.max_velocity_m_s,
            on_transition=transition,
        )
        self.engine.set_topology(config.topology_revision, [
            Receiver(r.receiver_id, r.area_id, r.area_name, r.kind, rssi_offset_db=r.rssi_offset_db, radius_m=r.radius_m)
            for r in config.receivers
        ])

    async def start(self) -> None:
        if self.client is None:
            self.client = BleGatewayClient(self.config.gateway_url, self.config.api_token.get_secret_value())
        try:
            await self.client.register(self.consumer_id, self.config.selected_device_handles)
            self.gateway_available = True
            await self.recover_snapshot()
        except GatewayError as exc:
            self.last_error = str(exc)
            self.gateway_available = False
        self.task = asyncio.create_task(self._run(), name=f"ble-presence-{self.consumer_id}")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.client:
            try:
                await self.client.unregister(self.consumer_id)
            except GatewayError:
                pass
            await self.client.close()

    @property
    def consumer_id(self) -> str:
        return self.config.consumer_id

    async def poll_once(self) -> None:
        if self.client is None:
            return
        try:
            page = await self.client.observations(self.consumer_id, after=self.cursor)
        except CursorGap:
            await self.recover_snapshot()
            return
        for observation in page.observations:
            self.engine.ingest(observation)
        self.cursor = max(self.cursor, page.cursor)
        self._poll_count += 1
        if self._poll_count % 15 == 0:
            await self.recover_snapshot()
        self.gateway_available = True
        self.last_error = None
        self.engine.evaluate(gateway_available=page.receiver_healthy)

    async def refresh_once(self) -> None:
        """Best-effort user refresh that records degradation instead of leaking task errors."""
        try:
            await self.poll_once()
        except (GatewayError, ValueError) as exc:
            self.gateway_available = False
            self.last_error = str(exc)
            self.engine.evaluate(gateway_available=False)

    async def recover_snapshot(self) -> None:
        if self.client is None:
            return
        payload = await self.client.snapshot(self.consumer_id)
        topology = payload.get("receivers", [])
        if isinstance(topology, list):
            receivers = []
            for raw in topology:
                if not isinstance(raw, dict) or not raw.get("receiver_id") or not raw.get("area_id"):
                    continue
                last_seen = raw.get("last_seen_at")
                receivers.append(Receiver(
                    str(raw["receiver_id"]), str(raw["area_id"]), str(raw.get("area_name", raw["area_id"])),
                    str(raw.get("receiver_kind", "unknown")), bool(raw.get("healthy", raw.get("online", True))),
                    datetime.fromisoformat(last_seen) if isinstance(last_seen, str) else None,
                    float(raw.get("rssi_offset_db", 0)), float(raw.get("radius_m", 20)),
                ))
            if receivers:
                self.engine.set_topology(int(payload.get("topology_revision", self.engine.topology_revision)), receivers)
        observations = payload.get("observations", [])
        if isinstance(observations, list):
            parsed = [Observation.from_payload(raw) for raw in observations if isinstance(raw, dict)]
            for observation in sorted(parsed, key=lambda item: item.sequence):
                self.engine.ingest(observation)
        self.cursor = int(payload.get("cursor", max((o.sequence for o in parsed), default=self.cursor) if isinstance(observations, list) else self.cursor))
        self.gateway_available = True
        self.last_error = None
        self.engine.evaluate(gateway_available=payload.get("receiver_healthy") is True)

    async def _run(self) -> None:
        while True:
            try:
                if not self.gateway_available and self.client is not None:
                    await self.client.register(self.consumer_id, self.config.selected_device_handles)
                await self.poll_once()
            except (GatewayError, ValueError) as exc:
                self.gateway_available = False
                self.last_error = str(exc)
                self.engine.evaluate(gateway_available=False)
            await asyncio.sleep(self.config.poll_interval_seconds)

    def entity_states(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(UTC)
        config_id = self.config.config_id or self.config.id
        return [{
            "id": entity_id(config_id, state.handle),
            "config_id": config_id,
            "device_handle": state.handle,
            "name": self.config.alias or f"Tracked BLE device {index + 1}",
            "presence": state.presence,
            "area_id": state.area_id,
            "area_name": state.area_name,
            "estimated_distance_m": state.estimated_distance_m,
            "distance_raw_m": state.raw_distance_m,
            "freshness_seconds": None if state.last_seen_at is None else max(0, round((now - state.last_seen_at).total_seconds(), 3)),
            "coverage_degraded": self.engine.coverage_degraded or not self.gateway_available,
            "topology_revision": self.engine.topology_revision,
            "area_switch_reason": state.area_switch_reason,
        } for index, state in enumerate(self.engine.devices.values())]
