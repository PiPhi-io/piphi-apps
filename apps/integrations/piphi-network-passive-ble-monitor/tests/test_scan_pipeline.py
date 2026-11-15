from __future__ import annotations

import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from piphi_network_passive_ble_monitor import state
from piphi_network_passive_ble_monitor.bthome import BTHOME_UUID
from piphi_network_passive_ble_monitor.gateway import GatewayError, Observation, ObservationPage
from piphi_network_passive_ble_monitor.schemas import DeviceConfig


def observation(sequence: int, payload: str, *, replayed: bool = False) -> Observation:
    ingested_at = datetime.now(timezone.utc).isoformat()
    return Observation(sequence, "ble_00000000000000000000000000000005", "receiver-1", "local", 1000 + sequence, ingested_at, replayed, -62, None, False, "random", (BTHOME_UUID,), {}, {BTHOME_UUID: bytes.fromhex(payload)})


class FakeGateway:
    def __init__(self) -> None:
        self.pages: list[ObservationPage | Exception] = []
        self.snapshot_page = ObservationPage((), 0, True)
        self.registered: list[tuple[str, str]] = []
        self.closed = False

    async def register(self, consumer_id: str, handle: str) -> None:
        self.registered.append((consumer_id, handle))

    async def unregister(self, consumer_id: str) -> None:
        return None

    async def snapshot(self, consumer_id: str, *, after: int = 0) -> ObservationPage:
        return self.snapshot_page

    async def observations(self, consumer_id: str, *, after: int) -> ObservationPage:
        item = self.pages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


def config(config_id: str = "ble-test") -> DeviceConfig:
    return DeviceConfig(id=config_id, gateway_url="https://gateway.test", gateway_token="secret-token", device_handle="ble_00000000000000000000000000000005", poll_interval_seconds=10, stale_after_seconds=30)


@pytest.mark.anyio
async def test_freshness_outage_and_measurement_age_are_independent(monkeypatch) -> None:
    fake = FakeGateway()
    sent: list[dict] = []
    monkeypatch.setattr(state, "gateway_client", lambda _config: fake)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **kwargs: sent.append(kwargs))
    await state.apply_config(config())
    try:
        fake.pages.append(ObservationPage((observation(1, "400001016102C40903C012"),), 1, True))
        await state.poll_config("ble-test", now=100)
        latest = state.registry.state_snapshots["ble-test"]["state"]
        assert latest["receiver_healthy"] is True
        assert latest["observation_fresh"] is True
        assert latest["sensor_available"] is True
        assert latest["temperature_c"] == 25.0
        assert latest["last_measurement_at"].endswith("+00:00")

        fake.pages.append(GatewayError("down"))
        with pytest.raises(GatewayError):
            await state.poll_config("ble-test", now=110)
        latest = state.registry.state_snapshots["ble-test"]["state"]
        assert latest["receiver_healthy"] is False
        assert latest["observation_fresh"] is True
        assert latest["sensor_available"] is False
        assert latest["temperature_c"] == 25.0

        fake.pages.append(ObservationPage((), 1, True))
        await state.poll_config("ble-test", now=131)
        latest = state.registry.state_snapshots["ble-test"]["state"]
        assert latest["observation_fresh"] is False
        assert latest["sensor_available"] is False
        assert latest["measurement_age_seconds"] == 31.0
    finally:
        await state.remove_config("ble-test")


@pytest.mark.anyio
async def test_replay_dedup_malformed_isolation_and_gap_snapshot(monkeypatch) -> None:
    fake = FakeGateway()
    monkeypatch.setattr(state, "gateway_client", lambda _config: fake)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **kwargs: None)
    await state.apply_config(config("replay-test"))
    try:
        fake.pages.append(ObservationPage((observation(1, "4000070161", replayed=True), observation(2, "4000070161", replayed=True)), 2, True, 1))
        await state.poll_config("replay-test", now=100)
        status = state._consumer_state["replay-test"]
        assert status.duplicate_packets == 1
        assert status.malformed_observations == 1
        assert state.registry.state_snapshots["replay-test"]["state"]["observation_fresh"] is False

        fake.pages.append(ObservationPage((observation(5, "4000080162"),), 5, True, gap=True))
        fake.snapshot_page = ObservationPage((observation(5, "4000080162", replayed=True),), 5, True)
        await state.poll_config("replay-test", now=200)
        assert status.gap_resyncs == 1
        assert state.registry.state_snapshots["replay-test"]["state"]["observation_fresh"] is False
    finally:
        await state.remove_config("replay-test")


def test_config_requires_opaque_handle_and_secret_is_redacted() -> None:
    with pytest.raises(ValueError, match="opaque"):
        DeviceConfig(id="bad", gateway_url="https://gateway.test", gateway_token="secret", device_handle="AA:BB:CC:DD:EE:FF")
    assert "secret-token" not in repr(config())


@pytest.mark.anyio
async def test_different_config_id_cannot_duplicate_gateway_device(monkeypatch) -> None:
    existing = config("existing-device")
    state.registry.set(existing.id, state.make_entry(existing))
    monkeypatch.setattr(
        state,
        "gateway_client",
        lambda _config: pytest.fail("duplicate must be rejected before gateway registration"),
    )
    try:
        with pytest.raises(HTTPException) as caught:
            await state.apply_config(config("duplicate-device"))
        assert caught.value.status_code == 409
        assert "existing-device" in str(caught.value.detail)
    finally:
        state.registry.remove(existing.id)
