from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from .gateway import Observation


@dataclass(frozen=True, slots=True)
class Receiver:
    receiver_id: str
    area_id: str
    area_name: str
    kind: str = "unknown"
    healthy: bool = True
    last_seen_at: datetime | None = None
    rssi_offset_db: float = 0.0
    radius_m: float = 20.0


@dataclass(slots=True)
class PairState:
    observed_monotonic_ms: int = -1
    sequence: int = -1
    ingested_at: datetime | None = None
    rssi_history: deque[int] = field(default_factory=lambda: deque(maxlen=8))
    raw_distance_m: float | None = None
    smoothed_distance_m: float | None = None


@dataclass(slots=True)
class DeviceState:
    handle: str
    presence: str = "unknown"
    area_id: str | None = None
    area_name: str | None = None
    area_switch_reason: str = "no_fresh_receiver"
    last_seen_at: datetime | None = None
    nearest_receiver_id: str | None = None
    estimated_distance_m: float | None = None
    raw_distance_m: float | None = None
    pairs: dict[str, PairState] = field(default_factory=dict)


class PresenceEngine:
    """Deterministic selected-device presence and room inference.

    Distances are RSSI estimates only. Area changes require the candidate to be
    both materially closer and stable for `switch_samples` consecutive updates.
    """

    def __init__(
        self,
        selected_handles: list[str],
        *,
        consider_home_seconds: int = 180,
        stale_seconds: int = 30,
        reference_power_dbm: int = -59,
        attenuation_factor: float = 2.0,
        smoothing_samples: int = 5,
        switch_margin_m: float = 1.0,
        switch_samples: int = 3,
        max_velocity_m_s: float = 12.0,
        on_transition: Callable[[str, DeviceState], None] | None = None,
    ):
        self.selected = frozenset(selected_handles)
        self.consider_home_seconds = consider_home_seconds
        self.stale_seconds = stale_seconds
        self.reference_power_dbm = reference_power_dbm
        self.attenuation_factor = attenuation_factor
        self.smoothing_samples = smoothing_samples
        self.switch_margin_m = switch_margin_m
        self.switch_samples = switch_samples
        self.max_velocity_m_s = max_velocity_m_s
        self.topology_revision = 0
        self.receivers: dict[str, Receiver] = {}
        self.devices = {handle: DeviceState(handle) for handle in self.selected}
        self.coverage_degraded = True
        self._pending_switch: dict[str, tuple[str, int]] = {}
        self._on_transition = on_transition

    def set_topology(self, revision: int, receivers: list[Receiver]) -> None:
        if revision < self.topology_revision:
            return
        self.topology_revision = revision
        self.receivers = {receiver.receiver_id: receiver for receiver in receivers}
        self.coverage_degraded = not receivers or any(not r.healthy for r in receivers)

    def ingest(self, observation: Observation, *, now: datetime | None = None) -> bool:
        if observation.device_handle not in self.selected:
            return False
        now = now or datetime.now(UTC)
        # Replayed data may rebuild histories but cannot make stale data present.
        if observation.replayed and (now - observation.ingested_at).total_seconds() > self.consider_home_seconds:
            return False
        receiver = self.receivers.get(observation.receiver_id)
        if receiver is None:
            return False
        device = self.devices[observation.device_handle]
        pair = device.pairs.setdefault(observation.receiver_id, PairState())
        order = (observation.observed_monotonic_ms, observation.sequence)
        if order <= (pair.observed_monotonic_ms, pair.sequence):
            return False
        raw = self._distance(observation.rssi + receiver.rssi_offset_db, observation.tx_power)
        if pair.smoothed_distance_m is not None and pair.ingested_at is not None:
            elapsed = max((observation.ingested_at - pair.ingested_at).total_seconds(), 0.001)
            if abs(raw - pair.smoothed_distance_m) / elapsed > self.max_velocity_m_s:
                raw = pair.smoothed_distance_m
        pair.observed_monotonic_ms, pair.sequence = order
        pair.ingested_at = observation.ingested_at
        pair.rssi_history.append(observation.rssi)
        pair.raw_distance_m = raw
        recent = list(pair.rssi_history)[-self.smoothing_samples :]
        pair.smoothed_distance_m = self._distance(sum(recent) / len(recent) + receiver.rssi_offset_db, observation.tx_power)
        device.last_seen_at = max(filter(None, (device.last_seen_at, observation.ingested_at)))
        if device.presence != "home":
            device.presence = "home"
            self._emit("presence.arrived", device)
        self.evaluate(now=now)
        return True

    def evaluate(self, *, now: datetime | None = None, gateway_available: bool = True) -> None:
        now = now or datetime.now(UTC)
        healthy = {rid for rid, receiver in self.receivers.items() if receiver.healthy}
        self.coverage_degraded = not healthy or any(not r.healthy for r in self.receivers.values())
        for device in self.devices.values():
            fresh = {
                rid: pair for rid, pair in device.pairs.items()
                if rid in healthy and pair.ingested_at is not None
                and (now - pair.ingested_at).total_seconds() <= self.stale_seconds
                and pair.smoothed_distance_m is not None
                and pair.smoothed_distance_m <= self.receivers[rid].radius_m
            }
            if not gateway_available or not healthy:
                device.presence = "unknown"
                device.area_id = device.area_name = device.nearest_receiver_id = None
                device.estimated_distance_m = device.raw_distance_m = None
                device.area_switch_reason = "coverage_degraded"
                continue
            if device.last_seen_at is None:
                device.presence = "unknown"
            elif (now - device.last_seen_at).total_seconds() > self.consider_home_seconds:
                if device.presence != "away":
                    device.presence = "away"
                    self._emit("presence.left", device)
                device.area_id = device.area_name = device.nearest_receiver_id = None
                device.estimated_distance_m = device.raw_distance_m = None
                device.area_switch_reason = "consider_home_expired"
                continue
            if not fresh:
                device.area_id = device.area_name = device.nearest_receiver_id = None
                device.estimated_distance_m = device.raw_distance_m = None
                device.area_switch_reason = "no_fresh_receiver"
                continue
            candidate_id, candidate = min(
                fresh.items(), key=lambda item: (cast(float, item[1].smoothed_distance_m), item[0])
            )
            candidate_distance = cast(float, candidate.smoothed_distance_m)
            receiver = self.receivers[candidate_id]
            if device.area_id is None:
                self._assign(device, receiver, candidate, "initial_fresh_receiver")
            elif receiver.area_id == device.area_id:
                self._pending_switch.pop(device.handle, None)
                self._assign(device, receiver, candidate, "same_area_nearest")
            else:
                current = [
                    cast(float, p.smoothed_distance_m)
                    for rid, p in fresh.items()
                    if self.receivers[rid].area_id == device.area_id
                ]
                current_distance = min(current) if current else math.inf
                materially_closer = candidate_distance + self.switch_margin_m < current_distance
                pending_id, count = self._pending_switch.get(device.handle, ("", 0))
                count = count + 1 if pending_id == receiver.area_id and materially_closer else (1 if materially_closer else 0)
                self._pending_switch[device.handle] = (receiver.area_id, count)
                if count >= self.switch_samples:
                    self._assign(device, receiver, candidate, "closer_receiver_stable_hysteresis")
                    self._pending_switch.pop(device.handle, None)

    def diagnostics(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        return {
            "selected_device_count": len(self.selected),
            "receiver_count": len(self.receivers),
            "healthy_receiver_count": sum(r.healthy for r in self.receivers.values()),
            "coverage_degraded": self.coverage_degraded,
            "topology_revision": self.topology_revision,
            "devices": [
                {"handle": f"opaque:{index + 1}", "presence": d.presence, "area_id": d.area_id,
                 "freshness_seconds": None if d.last_seen_at is None else max(0, (now - d.last_seen_at).total_seconds())}
                for index, d in enumerate(self.devices.values())
            ],
        }

    def _distance(self, rssi: float, tx_power: int | None) -> float:
        reference = tx_power if tx_power is not None else self.reference_power_dbm
        return round(10 ** ((reference - rssi) / (10 * self.attenuation_factor)), 3)

    def _assign(self, device: DeviceState, receiver: Receiver, pair: PairState, reason: str) -> None:
        device.area_id, device.area_name = receiver.area_id, receiver.area_name
        device.nearest_receiver_id = receiver.receiver_id
        device.raw_distance_m, device.estimated_distance_m = pair.raw_distance_m, pair.smoothed_distance_m
        device.area_switch_reason = reason

    def _emit(self, event: str, device: DeviceState) -> None:
        if self._on_transition:
            self._on_transition(event, device)
