from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from piphi_network_spi import create_app
from piphi_network_spi.routes import commands as command_routes
from piphi_network_spi import state as state_module


@pytest.fixture(autouse=True)
def clear_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    state_module.registry.entries.clear()
    state_module.registry.state_snapshots.clear()
    state_module.registry.recent_events.clear()
    monkeypatch.delenv("PIPHI_ALLOW_MOCK_HARDWARE", raising=False)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_discover_mock_requires_opt_in(client: TestClient) -> None:
    response = client.post("/discover", json={"inputs": {"adapter": "mock", "sensor_model": "bme680"}})

    assert response.status_code == 400
    assert "Mock hardware is disabled" in response.text


def test_initial_config_failure_leaves_no_registry_entry(client: TestClient) -> None:
    response = client.post("/config", json={"id": "spi-dev", "adapter": "mock", "sensor_model": "bme680"})

    assert response.status_code == 503
    assert "Mock hardware is disabled" in response.text
    assert state_module.registry.entries == {}
    assert state_module.registry.state_snapshots == {}


def test_reconfigure_failure_preserves_working_entry_and_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post(
        "/config", json={"id": "spi-dev", "adapter": "mock", "sensor_model": "bme280"}
    ).status_code == 200
    previous_entries = deepcopy(state_module.registry.entries)
    previous_states = deepcopy(state_module.registry.state_snapshots)
    monkeypatch.setattr(
        state_module,
        "read_state",
        lambda config: (_ for _ in ()).throw(RuntimeError("replacement probe failed")),
    )

    response = client.post(
        "/config",
        json={
            "id": "spi-dev",
            "adapter": "mock",
            "sensor_model": "bme680",
            "alias": "broken replacement",
        },
    )

    assert response.status_code == 503
    assert "replacement probe failed" in response.text
    assert state_module.registry.entries == previous_entries
    assert state_module.registry.state_snapshots == previous_states


def test_command_refresh_returns_503_and_updates_state_on_sensor_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post("/config", json={"id": "spi-dev", "adapter": "mock", "sensor_model": "bme680"}).status_code == 200

    def fake_read_state(_config):
        raise RuntimeError("spi read failed")

    monkeypatch.setattr(command_routes, "read_state", fake_read_state)

    response = client.post("/command", json={"command": "refresh", "device_id": "spi-dev"})

    assert response.status_code == 503
    assert "spi read failed" in response.text

    state = client.get("/state").json()
    snapshot = state["state_snapshots"]["spi-dev"]["state"]
    assert snapshot["connected"] is False
    assert snapshot["error"] == "spi read failed"
    assert any(event["event_type"] == "spi.sensor.refresh_failed" for event in state_module.registry.recent_events)


def test_config_sync_invalid_typed_config_returns_422(client: TestClient) -> None:
    response = client.post(
        "/config/sync",
        json={
            "container_id": "runtime-1",
            "configs": [
                {
                    "id": "spi-dev",
                    "adapter": "linux_spi",
                    "chip_select": "nope",
                }
            ],
            "deleted_config_ids": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "chip_select"


def test_state_without_configs_does_not_touch_hardware(client: TestClient) -> None:
    response = client.get("/state")

    assert response.status_code == 200
    assert response.json() == {"entries": {}, "state_snapshots": {}}


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "bad", "adapter": "unknown", "sensor_model": "bme280"},
        {"id": "bad", "adapter": "linux_spi", "bus": 1, "sensor_model": "bme280"},
        {"id": "bad", "adapter": "linux_spi", "chip_select": 2, "sensor_model": "bme280"},
        {"id": "bad", "adapter": "linux_spi", "baudrate": 1, "sensor_model": "bme280"},
        {"id": "bad", "adapter": "linux_spi", "sensor_model": "auto"},
    ],
)
def test_config_rejects_invalid_hardware_targets_before_io(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post("/config", json=payload)

    assert response.status_code == 422
    assert state_module.registry.entries == {}


def test_config_rejects_duplicate_target_claim(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    first = client.post(
        "/config", json={"id": "first", "adapter": "mock", "sensor_model": "bme280"}
    )
    duplicate = client.post(
        "/config", json={"id": "second", "adapter": "mock", "sensor_model": "bme680"}
    )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert "already claimed" in duplicate.text


def test_deconfigure_without_payload_returns_default_not_removed(client: TestClient) -> None:
    response = client.post("/deconfigure", json={})

    assert response.status_code == 200
    assert response.json()["removed"] is False
    assert response.json()["config_id"] == "spi-dev"


def test_command_rejects_unsupported_command(client: TestClient) -> None:
    response = client.post("/command", json={"command": "reboot"})

    assert response.status_code == 400
    assert "Unsupported command" in response.text


def test_command_refresh_replays_without_repeating_sensor_read(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post(
        "/config",
        json={"id": "spi-idempotent", "adapter": "mock", "sensor_model": "bme680"},
    ).status_code == 200
    reads = 0

    def fake_read_state(_config):
        nonlocal reads
        reads += 1
        return {"connected": True, "temperature_c": 21.5}

    monkeypatch.setattr(command_routes, "read_state", fake_read_state)
    headers = {"X-PiPhi-Idempotency-Key": "spi-refresh-idempotency-1"}
    payload = {"command": "refresh", "device_id": "spi-idempotent"}
    first = client.post("/command", json=payload, headers=headers)
    replay = client.post("/command", json=payload, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert reads == 1


def test_deconfigure_after_config_returns_removed_true_and_clears_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post("/config", json={"id": "spi-dev", "adapter": "mock", "sensor_model": "bme680"}).status_code == 200

    response = client.post("/deconfigure", json={"config_id": "spi-dev"})

    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert state_module.registry.entries == {}


def test_config_sync_replaces_existing_config_and_reports_removed_ids(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post("/config", json={"id": "old-dev", "adapter": "mock", "sensor_model": "bme280"}).status_code == 200

    response = client.post(
        "/config/sync",
        json={
            "container_id": "runtime-1",
            "configs": [
                {
                    "id": "new-dev",
                    "adapter": "mock",
                    "sensor_model": "bme680",
                }
            ],
            "deleted_config_ids": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == ["new-dev"]
    assert body["removed"] == ["old-dev"]
    assert body["active_config_ids"] == ["new-dev"]


def test_entities_include_gas_capability_for_bme680(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post("/config", json={"id": "spi-dev", "adapter": "mock", "sensor_model": "bme680"}).status_code == 200

    response = client.get("/entities")

    assert response.status_code == 200
    assert "gas_ohms" in response.json()["entities"][0]["capabilities"]


def test_state_telemetry_uses_stable_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        state_module,
        "schedule_telemetry_delivery",
        lambda **kwargs: captured.update(kwargs),
    )

    state_module.schedule_state_telemetry(
        {
            "config_id": "spi-config-1",
            "device_id": "spi-device-1",
            "container_id": "container-1",
        },
        {
            "connected": True,
            "pressure_hpa": 1013.2,
            "sampled_at": "2026-07-26T12:00:00Z",
            "error": "not forwarded",
        },
    )

    assert captured["config_id"] == "spi-config-1"
    assert captured["device_id"] == "spi-device-1"
    assert captured["container_id"] == "container-1"
    assert captured["metrics"] == {"connected": True, "pressure_hpa": 1013.2}
    assert captured["units"] == {"connected": "bool", "pressure_hpa": "hPa"}
    assert captured["timestamp"] == "2026-07-26T12:00:00Z"
