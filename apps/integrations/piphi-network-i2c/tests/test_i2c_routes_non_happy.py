from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from piphi_network_i2c import create_app
from piphi_network_i2c import sensors
from piphi_network_i2c.routes import commands as command_routes
from piphi_network_i2c import state as state_module


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


def test_discover_mcp2221a_without_easy_mcp_returns_empty_list(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sensors,
        "_import_easy_mcp2221",
        lambda: (_ for _ in ()).throw(ImportError("EasyMCP2221 missing")),
    )

    response = client.post("/discover", json={"inputs": {"adapter": "mcp2221a", "sensor_model": "auto"}})

    assert response.status_code == 200
    assert response.json()["devices"] == []


def test_config_with_mcp2221a_without_easy_mcp_records_error_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sensors,
        "_import_easy_mcp2221",
        lambda: (_ for _ in ()).throw(ImportError("EasyMCP2221 missing")),
    )

    response = client.post("/config", json={"id": "i2c-dev", "adapter": "mcp2221a", "sensor_model": "bme280"})

    assert response.status_code == 200

    state = client.get("/state").json()
    snapshot = state["state_snapshots"]["i2c-dev"]["state"]
    assert snapshot["connected"] is False
    assert "EasyMCP2221 missing" in snapshot["error"]


def test_config_with_mock_without_opt_in_records_error_state(client: TestClient) -> None:
    response = client.post("/config", json={"id": "i2c-dev", "adapter": "mock", "sensor_model": "bme680"})

    assert response.status_code == 200

    state = client.get("/state").json()
    snapshot = state["state_snapshots"]["i2c-dev"]["state"]
    assert snapshot["connected"] is False
    assert "Mock hardware is disabled" in snapshot["error"]


def test_command_refresh_returns_503_and_updates_state_on_sensor_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post("/config", json={"id": "i2c-dev", "adapter": "mock", "sensor_model": "bme680"}).status_code == 200

    def fake_read_state(_config):
        raise RuntimeError("sensor read failed")

    monkeypatch.setattr(command_routes, "read_state", fake_read_state)

    response = client.post("/command", json={"command": "refresh", "device_id": "i2c-dev"})

    assert response.status_code == 503
    assert "sensor read failed" in response.text

    state = client.get("/state").json()
    snapshot = state["state_snapshots"]["i2c-dev"]["state"]
    assert snapshot["connected"] is False
    assert snapshot["error"] == "sensor read failed"
    assert any(event["event_type"] == "i2c.sensor.refresh_failed" for event in state_module.registry.recent_events)


def test_config_sync_invalid_typed_config_returns_422(client: TestClient) -> None:
    response = client.post(
        "/config/sync",
        json={
            "container_id": "runtime-1",
            "configs": [
                {
                    "id": "i2c-dev",
                    "adapter": "linux_i2c",
                    "bus": "not-a-number",
                }
            ],
            "deleted_config_ids": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "bus"


def test_state_without_configs_reports_sensor_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_state(_config):
        raise RuntimeError("i2c unavailable")

    monkeypatch.setattr(state_module, "read_state", fake_read_state)

    response = client.get("/state")

    assert response.status_code == 200
    assert response.json()["state"] == {"connected": False, "error": "i2c unavailable"}


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
        json={"id": "i2c-idempotent", "adapter": "mock", "sensor_model": "bme680"},
    ).status_code == 200
    reads = 0

    def fake_read_state(_config):
        nonlocal reads
        reads += 1
        return {"connected": True, "temperature_c": 21.5}

    monkeypatch.setattr(command_routes, "read_state", fake_read_state)
    headers = {"X-PiPhi-Idempotency-Key": "i2c-refresh-idempotency-1"}
    payload = {"command": "refresh", "device_id": "i2c-idempotent"}
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
    assert client.post("/config", json={"id": "i2c-dev", "adapter": "mock", "sensor_model": "bme680"}).status_code == 200

    response = client.post("/deconfigure", json={"config_id": "i2c-dev"})

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
    assert client.post("/config", json={"id": "i2c-dev", "adapter": "mock", "sensor_model": "bme680"}).status_code == 200

    response = client.get("/entities")

    assert response.status_code == 200
    assert "gas_ohms" in response.json()["entities"][0]["capabilities"]


def test_entities_include_pm_capabilities_for_pmsa003i(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post("/config", json={"id": "pm-dev", "adapter": "mock", "sensor_model": "pmsa003i"}).status_code == 200

    response = client.get("/entities")

    assert response.status_code == 200
    capabilities = response.json()["entities"][0]["capabilities"]
    assert "pm2_5_standard_ugm3" in capabilities
    assert "particles_0_3um_per_0_1l" in capabilities
    assert "temperature_c" not in capabilities


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
            "config_id": "i2c-config-1",
            "device_id": "i2c-device-1",
            "container_id": "container-1",
        },
        {
            "connected": True,
            "temperature_c": 22.5,
            "sampled_at": "2026-07-26T12:00:00Z",
            "error": "not forwarded",
        },
    )

    assert captured["config_id"] == "i2c-config-1"
    assert captured["device_id"] == "i2c-device-1"
    assert captured["container_id"] == "container-1"
    assert captured["metrics"] == {"connected": True, "temperature_c": 22.5}
    assert captured["units"] == {"connected": "bool", "temperature_c": "C"}
    assert captured["timestamp"] == "2026-07-26T12:00:00Z"
