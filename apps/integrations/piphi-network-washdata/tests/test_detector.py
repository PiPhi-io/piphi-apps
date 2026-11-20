import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from piphi_runtime_kit_python import SourceTelemetryPoint

from piphi_network_washdata.detector import apply_points
from piphi_network_washdata.persistence import CycleState
from piphi_network_washdata.schemas import DeviceConfig


def _point(index: int, power: float) -> SourceTelemetryPoint:
    at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index * 10)
    return SourceTelemetryPoint(
        event_id=f"event-{index}",
        metric="power_w",
        value=power,
        value_kind="number",
        unit="W",
        collected_at=at,
        received_at=at,
    )


def test_deterministic_debounced_cycle_and_replay_deduplication() -> None:
    config = DeviceConfig(
        id="config-1",
        start_threshold_w=10,
        stop_threshold_w=5,
        start_debounce_samples=2,
        stop_debounce_samples=3,
    )
    initial = CycleState(
        config_id="config-1",
        binding_id="binding-1",
        binding_key="appliance_power",
        canonical_device_id="device-1",
    )
    fixture = json.loads((Path(__file__).parent / "fixtures" / "power-cycle.json").read_text())
    points = [_point(index, power) for index, power in enumerate(fixture["power_w"])]

    finished, accepted, events = apply_points(initial, points, config, already_processed=set())
    assert accepted == [point.event_id for point in points]
    assert [item[0] for item in events] == ["cycle.started", "cycle.finished"]
    assert finished.cycle_state == "idle"
    assert finished.lifetime_cycle_count == 1
    assert finished.cycle_duration_s == 50
    assert finished.peak_power_w == 40
    assert finished.cycle_energy_kwh > 0

    replayed, replay_ids, replay_events = apply_points(
        finished, points, config, already_processed=set(accepted)
    )
    assert replay_ids == []
    assert replay_events == []
    assert replayed.lifetime_cycle_count == 1
