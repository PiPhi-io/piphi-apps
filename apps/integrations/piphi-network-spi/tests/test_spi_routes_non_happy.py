from __future__ import annotations

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


def test_config_with_mock_without_opt_in_records_error_state(client: TestClient) -> None:
    response = client.post("/config", json={"id": "spi-dev", "adapter": "mock", "sensor_model": "bme680"})

    assert response.status_code == 200

    state = client.get("/state").json()
    snapshot = state["state_snapshots"]["spi-dev"]["state"]
    assert snapshot["connected"] is False
    assert "Mock hardware is disabled" in snapshot["error"]


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


def test_state_without_configs_reports_sensor_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_state(_config):
        raise RuntimeError("spi unavailable")

    monkeypatch.setattr(state_module, "read_state", fake_read_state)

    response = client.get("/state")

    assert response.status_code == 200
    assert response.json()["state"] == {"connected": False, "error": "spi unavailable"}


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
