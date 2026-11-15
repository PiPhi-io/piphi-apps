from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from piphi_network_bermuda_presence.gateway import Observation
from piphi_network_bermuda_presence.inference import PresenceEngine, Receiver

TRACE_IDS = {case["id"] for case in json.loads((Path(__file__).parent / "fixtures/presence-traces.json").read_text())["cases"]}
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def observation(sequence: int, receiver: str, rssi: int, seconds: int = 0, *, replayed: bool = False, monotonic: int | None = None) -> Observation:
    return Observation(sequence, "opaque-phone", receiver, "proxy", monotonic if monotonic is not None else sequence * 1000,
                       T0 + timedelta(seconds=seconds), replayed, rssi, -59, False, "random", (), None, None)


def engine(events: list[str]) -> PresenceEngine:
    value = PresenceEngine(["opaque-phone"], consider_home_seconds=60, stale_seconds=10, switch_samples=2,
                           switch_margin_m=.5, max_velocity_m_s=1000,
                           on_transition=lambda event, _device: events.append(event))
    value.set_topology(4, [Receiver("a", "kitchen", "Kitchen"), Receiver("b", "office", "Office")])
    return value


def test_fixture_covers_required_traces() -> None:
    assert TRACE_IDS == {"approach", "departure", "equal_rooms", "occlusion", "duplicates", "delayed_out_of_order",
                         "receiver_outage", "restart_replay", "no_stale_area_resurrection"}


def test_approach_equal_rooms_duplicates_and_out_of_order() -> None:
    events: list[str] = []
    value = engine(events)
    assert value.ingest(observation(1, "a", -62), now=T0)
    assert value.devices["opaque-phone"].area_id == "kitchen"
    assert not value.ingest(observation(1, "a", -20), now=T0)  # duplicate
    assert not value.ingest(observation(2, "a", -20, monotonic=500), now=T0)  # delayed
    value.ingest(observation(3, "b", -62, 1), now=T0 + timedelta(seconds=1))
    assert value.devices["opaque-phone"].area_id == "kitchen"  # equal rooms do not flap
    value.ingest(observation(4, "b", -45, 2), now=T0 + timedelta(seconds=2))
    value.ingest(observation(5, "b", -44, 3), now=T0 + timedelta(seconds=3))
    assert value.devices["opaque-phone"].area_id == "office"
    assert value.devices["opaque-phone"].area_switch_reason == "closer_receiver_stable_hysteresis"
    assert events == ["presence.arrived"]


def test_departure_is_idempotent_and_outage_is_unknown() -> None:
    events: list[str] = []
    value = engine(events)
    value.ingest(observation(1, "a", -50), now=T0)
    value.evaluate(now=T0 + timedelta(seconds=70), gateway_available=False)
    assert value.devices["opaque-phone"].presence == "unknown"
    assert "presence.left" not in events
    value.evaluate(now=T0 + timedelta(seconds=70), gateway_available=True)
    value.evaluate(now=T0 + timedelta(seconds=80), gateway_available=True)
    assert value.devices["opaque-phone"].presence == "away"
    assert events.count("presence.left") == 1


def test_stale_replay_and_stale_pair_cannot_resurrect_area() -> None:
    events: list[str] = []
    value = engine(events)
    value.ingest(observation(1, "a", -50), now=T0)
    value.evaluate(now=T0 + timedelta(seconds=20))
    assert value.devices["opaque-phone"].area_id is None
    assert not value.ingest(observation(2, "a", -30, replayed=True), now=T0 + timedelta(seconds=120))
    value.evaluate(now=T0 + timedelta(seconds=120))
    state = value.devices["opaque-phone"]
    assert state.presence == "away"
    assert state.area_id is None


def test_implausible_velocity_guard_bounds_occlusion_jump() -> None:
    value = PresenceEngine(["opaque-phone"], max_velocity_m_s=.1)
    value.set_topology(1, [Receiver("a", "room", "Room")])
    value.ingest(observation(1, "a", -50), now=T0)
    before = value.devices["opaque-phone"].pairs["a"].smoothed_distance_m
    value.ingest(observation(2, "a", -100, 1), now=T0 + timedelta(seconds=1))
    pair = value.devices["opaque-phone"].pairs["a"]
    assert pair.raw_distance_m == before


def test_diagnostics_redact_opaque_handles() -> None:
    value = engine([])
    diagnostics = value.diagnostics(now=T0)
    assert "opaque-phone" not in json.dumps(diagnostics)
    assert diagnostics["devices"][0]["handle"] == "opaque:1"
