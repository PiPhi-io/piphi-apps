from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from piphi_runtime_kit_python import (
    CoreSourceUnavailableError,
    CoreUnavailableError,
    SourceBinding,
    SourceTelemetryPage,
    SourceTelemetryPoint,
)

from piphi_network_washdata import state
from piphi_network_washdata.persistence import CycleStore
from piphi_network_washdata.schemas import DeviceConfig


class FakeSourceClient:
    def __init__(self) -> None:
        self.pages: list[SourceTelemetryPage | Exception] = []
        self.bindings = [
            SourceBinding(
                binding_id="binding-1",
                binding_key="appliance_power",
                consumer_config_id="config-1",
                source_identity_id="source-1",
                canonical_device_id="device-1",
                source_status="active",
                stale_after_seconds=60,
            )
        ]

    async def list_bindings(self, **_kwargs):
        return self.bindings

    async def read_telemetry(self, **_kwargs):
        item = self.pages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _page(cursor: str, powers: list[float], *, stale: bool = False) -> SourceTelemetryPage:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    points = [
        SourceTelemetryPoint(
            event_id=f"event-{index}",
            metric="power_w",
            value=power,
            value_kind="number",
            unit="W",
            collected_at=base + timedelta(seconds=index * 10),
            received_at=base + timedelta(seconds=index * 10),
        )
        for index, power in enumerate(powers)
    ]
    return SourceTelemetryPage(
        binding_id="binding-1",
        canonical_device_id="device-1",
        points=points,
        next_cursor=cursor,
        has_more=False,
        stale=stale,
        latest_collected_at=points[-1].collected_at if points else None,
    )


@pytest.fixture(autouse=True)
async def isolated_runtime(tmp_path, monkeypatch: pytest.MonkeyPatch):
    fake = FakeSourceClient()
    monkeypatch.setattr(state, "source_client", fake)
    monkeypatch.setattr(state, "store", CycleStore(tmp_path / "state.sqlite3"))
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
    state.runtime_data.configs.clear()
    state.runtime_data.locks.clear()
    state.runtime_data.next_poll_at.clear()
    yield fake


@pytest.mark.anyio
async def test_source_page_is_committed_replayed_and_recovered(
    isolated_runtime: FakeSourceClient,
) -> None:
    await state.apply_config(
        DeviceConfig(
            id="config-1",
            container_id="container-1",
            start_debounce_samples=2,
            stop_debounce_samples=3,
        )
    )
    isolated_runtime.pages.append(_page("cursor-1", [0, 20, 30, 40, 2, 1, 0]))
    result = await state.refresh_config("config-1")
    assert result["lifetime_cycle_count"] == 1
    assert state.store.load("config-1").next_cursor == "cursor-1"

    # Simulate a process restart: volatile registry/config state disappears,
    # while the SQLite volume and Core-owned binding remain.
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.runtime_data.configs.clear()
    state.runtime_data.locks.clear()
    state.runtime_data.next_poll_at.clear()
    await state.apply_config(
        DeviceConfig(
            id="config-1",
            container_id="container-1",
            start_debounce_samples=2,
            stop_debounce_samples=3,
        )
    )
    restarted = state.store.load("config-1")
    assert restarted is not None and restarted.next_cursor == "cursor-1"
    assert restarted.lifetime_cycle_count == 1

    isolated_runtime.pages.append(_page("cursor-2", [0, 20, 30, 40, 2, 1, 0]))
    replay = await state.refresh_config("config-1")
    assert replay["processed_event_count"] == 0
    assert replay["lifetime_cycle_count"] == 1

    isolated_runtime.pages.extend([_page("cursor-3", [], stale=True), _page("cursor-4", [])])
    assert (await state.refresh_config("config-1"))["detector_status"] == "stale"
    assert (await state.refresh_config("config-1"))["detector_status"] == "healthy"
    event_types = [event["event_type"] for event in state.registry.recent_events]
    assert event_types.count("cycle.started") == 1
    assert event_types.count("cycle.finished") == 1
    assert "detector.degraded" in event_types
    assert "detector.recovered" in event_types


@pytest.mark.anyio
async def test_unavailable_source_preserves_last_state_as_stale(
    isolated_runtime: FakeSourceClient,
) -> None:
    await state.apply_config(DeviceConfig(id="config-1", container_id="container-1"))
    isolated_runtime.pages.append(
        CoreSourceUnavailableError(
            operation="source_telemetry_read",
            url="http://core",
            message="gone",
            retryable=False,
            status_code=410,
        )
    )
    result = await state.refresh_config("config-1")
    assert result["detector_status"] == "unavailable"
    assert result["stale"] is True


@pytest.mark.anyio
async def test_transient_source_failure_is_degraded_and_recoverable(
    isolated_runtime: FakeSourceClient,
) -> None:
    await state.apply_config(DeviceConfig(id="config-1", container_id="container-1"))
    isolated_runtime.pages.extend(
        [
            CoreUnavailableError(
                operation="source_telemetry_read",
                url="http://core",
                message="offline",
                retryable=True,
            ),
            _page("cursor-1", []),
        ]
    )
    assert (await state.refresh_config("config-1"))["detector_status"] == "degraded"
    assert (await state.refresh_config("config-1"))["detector_status"] == "healthy"


@pytest.mark.anyio
async def test_configuration_requires_one_matching_binding(
    isolated_runtime: FakeSourceClient,
) -> None:
    isolated_runtime.bindings = []
    with pytest.raises(HTTPException, match="source_binding_missing"):
        await state.apply_config(DeviceConfig(id="config-1", container_id="container-1"))

    binding = SourceBinding(
        binding_id="binding-2",
        binding_key="appliance_power",
        consumer_config_id="config-1",
        source_identity_id="source-2",
        canonical_device_id="device-2",
        source_status="active",
        stale_after_seconds=60,
    )
    isolated_runtime.bindings = [binding, binding.model_copy(update={"binding_id": "binding-3"})]
    with pytest.raises(HTTPException, match="source_binding_ambiguous"):
        await state.apply_config(DeviceConfig(id="config-1", container_id="container-1"))
