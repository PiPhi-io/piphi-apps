from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from piphi_network_i2c import create_app, sensors
from piphi_network_i2c import state as state_module
from piphi_network_i2c.routes import commands as command_routes
from piphi_network_i2c.routes import discovery as discovery_routes


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


def test_discover_rejects_unselectable_usb_backend(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sensors,
        "_import_easy_mcp2221",
        lambda: (_ for _ in ()).throw(ImportError("EasyMCP2221 missing")),
    )

    response = client.post("/discover", json={"inputs": {"adapter": "mcp2221a", "sensor_model": "auto"}})

    assert response.status_code == 400
    assert "Unsupported I2C adapter" in response.text


def test_discovery_permission_preflight_fails_before_io(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    io_attempted = False

    def forbidden_io(_config):
        nonlocal io_attempted
        io_attempted = True
        raise AssertionError("discovery I/O must not run")

    monkeypatch.setattr(
        discovery_routes,
        "preflight_target",
        lambda _config: (_ for _ in ()).throw(PermissionError("mapped node denied")),
    )
    monkeypatch.setattr(discovery_routes, "discover_devices", forbidden_io)

    response = client.post(
        "/discover",
        json={
            "inputs": {
                "adapter": "linux_i2c",
                "adapter_id": "display-one",
                "bus": 1,
                "address": "0x76",
                "sensor_model": "bme280",
            }
        },
    )

    assert response.status_code == 503
    assert "permission_denied" in response.text
    assert io_attempted is False


def test_initial_config_failure_leaves_no_registry_entry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sensors,
        "_import_easy_mcp2221",
        lambda: (_ for _ in ()).throw(ImportError("EasyMCP2221 missing")),
    )

    response = client.post(
        "/config",
        json={"id": "i2c-dev", "adapter": "mcp2221a", "address": "0x76", "sensor_model": "bme280"},
    )

    assert response.status_code == 422
    assert "mcp2221a" in response.text
    assert state_module.registry.entries == {}
    assert state_module.registry.state_snapshots == {}


def test_config_with_mock_without_opt_in_fails_without_registration(client: TestClient) -> None:
    response = client.post("/config", json={"id": "i2c-dev", "adapter": "mock", "sensor_model": "bme680"})

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
        "/config",
        json={"id": "i2c-dev", "adapter": "mock", "address": "0x76", "sensor_model": "bme280"},
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
            "id": "i2c-dev",
            "adapter": "mock",
            "address": "0x76",
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
    assert client.post("/config", json={"id": "i2c-dev", "adapter": "mock", "sensor_model": "bme680"}).status_code == 200

    def fake_read_state(_config):
        raise RuntimeError("sensor read failed")

    monkeypatch.setattr(command_routes, "read_state", fake_read_state)

    response = client.post("/command", json={"command": "refresh", "device_id": "i2c-dev"})

    assert response.status_code == 503
    assert "io_error" in response.text

    state = client.get("/state").json()
    snapshot = state["state_snapshots"]["i2c-dev"]["state"]
    assert snapshot["connected"] is False
    assert snapshot["error_class"] == "io_error"
    assert snapshot["availability"] == "stale"
    assert "sensor read failed" not in response.text
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


def test_state_without_configs_does_not_touch_hardware(client: TestClient) -> None:
    response = client.get("/state")

    assert response.status_code == 200
    assert response.json() == {"entries": {}, "state_snapshots": {}}


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "bad", "adapter": "unknown", "address": "0x76", "sensor_model": "bme280"},
        {"id": "bad", "adapter": "linux_i2c", "address": "0x02", "sensor_model": "bme280"},
        {"id": "bad", "adapter": "linux_i2c", "address": "0x76", "bus": -1, "sensor_model": "bme280"},
        {"id": "bad", "adapter": "linux_i2c", "address": "0x76", "sensor_model": "aht20"},
        {"id": "bad", "adapter": "linux_i2c", "sensor_model": "bme280"},
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
        "/config",
        json={
            "id": "first",
            "adapter": "mock",
            "adapter_id": "display-one",
            "address": "0x76",
            "sensor_model": "bme280",
        },
    )
    io_attempts = 0

    def forbidden_io(_config):
        nonlocal io_attempts
        io_attempts += 1
        raise AssertionError("duplicate claim must not reach hardware I/O")

    monkeypatch.setattr(state_module, "read_state", forbidden_io)
    monkeypatch.setattr(
        state_module,
        "preflight_target",
        lambda _config: (_ for _ in ()).throw(AssertionError("duplicate claim must not reach preflight")),
    )
    duplicate = client.post(
        "/config",
        json={
            "id": "second",
            "adapter": "mock",
            "adapter_id": "display-two",
            "address": "0x76",
            "sensor_model": "bme680",
        },
    )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert "already claimed" in duplicate.text
    assert io_attempts == 0


def test_failed_config_releases_target_reservation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    monkeypatch.setattr(
        state_module,
        "read_state",
        lambda _config: (_ for _ in ()).throw(RuntimeError("probe failed")),
    )

    failed = client.post(
        "/config",
        json={"id": "failed", "adapter": "mock", "address": "0x76", "sensor_model": "bme280"},
    )
    monkeypatch.setattr(state_module, "read_state", sensors.mock_state)
    replacement = client.post(
        "/config",
        json={"id": "replacement", "adapter": "mock", "address": "0x76", "sensor_model": "bme280"},
    )

    assert failed.status_code == 503
    assert replacement.status_code == 200
    assert set(state_module.registry.entries) == {"replacement"}


def test_background_refresh_records_offline_state_once_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    config = state_module.I2CSensorRuntimeConfig(
        id="background-i2c", adapter="mock", address="0x76", sensor_model="bme280"
    )
    entry = state_module.entry_for_config(config)
    state_module.registry.set(config.id, entry)
    state_module.registry.update_state(
        config.id,
        {"connected": True, "availability": "available", "temperature_c": 21.0},
        device_id=entry["device_id"],
    )
    attempts = 0

    def fail_once(_config):
        nonlocal attempts
        attempts += 1
        raise PermissionError("offline")

    monkeypatch.setattr(state_module, "read_state", fail_once)
    asyncio.run(state_module.refresh_all_state())

    failed = state_module.registry.state_snapshots[config.id]["state"]
    assert attempts == 1
    assert failed["availability"] == "stale"
    assert failed["error_class"] == "permission_denied"

    monkeypatch.setattr(state_module, "read_state", lambda _config: {"connected": True, "temperature_c": 22.0})
    asyncio.run(state_module.refresh_all_state())

    recovered = state_module.registry.state_snapshots[config.id]["state"]
    assert recovered["availability"] == "available"
    assert any(event["event_type"] == "i2c.sensor.recovered" for event in state_module.registry.recent_events)


def test_command_rejects_unsupported_command(client: TestClient) -> None:
    response = client.post("/command", json={"command": "reboot"})

    assert response.status_code == 400
    assert "Unsupported command" in response.text


def test_refresh_classifies_recovery_transition(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    assert client.post(
        "/config", json={"id": "recovering", "adapter": "mock", "sensor_model": "bme280"}
    ).status_code == 200
    state_module.registry.update_state(
        "recovering", {"connected": False, "availability": "unavailable", "error_class": "unavailable"}
    )

    response = client.post("/command", json={"command": "refresh", "device_id": "recovering"})

    assert response.status_code == 200
    snapshot = client.get("/state").json()["state_snapshots"]["recovering"]["state"]
    assert snapshot["availability"] == "available"
    assert any(event["event_type"] == "i2c.sensor.recovered" for event in state_module.registry.recent_events)


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


@pytest.mark.parametrize("sensor_model", ["aht20", "pmsa003i"])
def test_removed_unselectable_models_are_rejected_for_all_backends(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    sensor_model: str,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    response = client.post(
        "/config",
        json={"id": "unsupported", "adapter": "mock", "sensor_model": sensor_model},
    )

    assert response.status_code == 422
    assert state_module.registry.entries == {}


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
    assert captured["auth_context"] is state_module.runtime.auth
    assert captured["metrics"] == {"connected": True, "temperature_c": 22.5}
    assert captured["units"] == {"connected": "bool", "temperature_c": "C"}
    assert captured["timestamp"] == "2026-07-26T12:00:00Z"
