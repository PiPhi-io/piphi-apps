from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from piphi_runtime_testkit_python import (
    assert_event_sent,
    assert_telemetry_sent,
    build_config_payload,
    build_config_snapshot,
    build_runtime_headers,
)

from piphi_network_tp_link.app import app
from piphi_network_tp_link.lib.store import registry, runtime_context

config_module = importlib.import_module("piphi_network_tp_link.contract.config.routes")
command_module = importlib.import_module(
    "piphi_network_tp_link.contract.command.router"
)
discovery_module = importlib.import_module(
    "piphi_network_tp_link.contract.discovery.discovery"
)
kasa_client_module = importlib.import_module("piphi_network_tp_link.lib.kasa_client")
state_module = importlib.import_module("piphi_network_tp_link.contract.state.router")


def test_tp_link_automation_registry_matches_declared_behavior_commands() -> None:
    behaviors_path = Path(__file__).resolve().parents[1] / "src" / "behaviors.json"
    behaviors = json.loads(behaviors_path.read_text(encoding="utf-8"))
    declared_commands = {
        action["runtime"]["command"]
        for device in behaviors["devices"]
        for action in device.get("actions", [])
    }
    registered_commands = {
        definition.command
        for definition in command_module.automation_registry.action_definitions
    }

    assert registered_commands == declared_commands


def test_tp_link_static_behavior_conditions_use_emitted_telemetry_fields() -> None:
    behaviors_path = Path(__file__).resolve().parents[1] / "src" / "behaviors.json"
    behaviors = json.loads(behaviors_path.read_text(encoding="utf-8"))
    emitted_metrics = config_module._build_telemetry_metrics(
        {
            "is_on": True,
            "device_type": "DeviceType.Plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }
    )
    dynamic_condition_ids = {"feature_equals", "feature_in_range"}
    declared_fields = {
        condition["runtime"]["field"]
        for device in behaviors["devices"]
        for condition in device.get("conditions", [])
        if condition["id"] not in dynamic_condition_ids
    }

    assert declared_fields <= emitted_metrics.keys()

    template_fields = {
        template["config"]["conditionTree"]["field"]
        for template in behaviors.get("templates", [])
        if isinstance(template.get("config", {}).get("conditionTree"), dict)
        and template["config"]["conditionTree"].get("field")
    }
    assert template_fields <= emitted_metrics.keys()


@pytest.mark.parametrize(
    ("device_class", "capabilities", "default_widget"),
    [
        ("light", ["switch", "brightness"], "device-control"),
        ("plug", ["switch", "energy_power"], "smart-plug"),
        ("plug", ["switch"], "device-control"),
        ("energy", ["energy_power"], "energy-monitor"),
        ("sensor", ["temperature", "humidity"], "environment-monitor"),
    ],
)
def test_dashboard_hints_prefer_integration_owned_experiences(
    device_class: str, capabilities: list[str], default_widget: str
) -> None:
    hints = importlib.import_module(
        "piphi_network_tp_link.contract.entities.router"
    )._dashboard_hints(device_class, capabilities)

    assert hints["default_widget"] == default_widget
    assert default_widget in hints["allowed_widgets"]
    assert all(
        widget in {"device-control", "energy-monitor", "smart-plug", "environment-monitor"}
        for widget in hints["allowed_widgets"]
    )


def test_telemetry_metrics_promote_environment_feature_values() -> None:
    metrics = config_module._build_telemetry_metrics(
        {
            "is_on": False,
            "features": {
                "current_temperature": {"value": 22.6},
                "relative_humidity": {"value": "47"},
            },
        }
    )

    assert metrics["temperature"] == 22.6
    assert metrics["humidity"] == 47.0


def test_kl110_current_consumption_is_promoted_to_current_power_telemetry() -> None:
    features = {
        "current_consumption": {
            "id": "current_consumption",
            "name": "Current consumption",
            "type": "1",
            "value": 0.0,
            "unit": "W",
        },
        "consumption_today": {
            "id": "consumption_today",
            "name": "Today's consumption",
            "type": "1",
            "value": 0.0,
            "unit": "kWh",
        },
        "consumption_this_month": {
            "id": "consumption_this_month",
            "name": "This month's consumption",
            "type": "1",
            "value": 0.041,
            "unit": "kWh",
        },
    }

    energy = kasa_client_module._extract_energy_metrics(features)
    capabilities = kasa_client_module._derive_capabilities_from_features(features)
    metrics = config_module._build_telemetry_metrics(
        {"is_on": False, "energy": energy}
    )

    assert energy == {
        "current_power_w": 0.0,
        "today_kwh": 0.0,
        "month_kwh": 0.041,
    }
    assert "energy_power" in capabilities
    assert metrics["power"] == 0.0
    assert metrics["energy_power"] == 0.0
    assert metrics["current_power_w"] == 0.0


class _DummyTask:
    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        return None


class _FakeFeature:
    attribute_setter = True

    def __init__(self) -> None:
        self.value = None

    async def set_value(self, value) -> None:
        self.value = value


class _FakeKasaDevice:
    host = "192.168.1.25"
    alias = "Desk Plug"
    model = "KP125M"
    device_type = "plug"
    mac = "00:11:22:33:44:55"
    sys_info = {}
    children = []
    features: dict[str, _FakeFeature]

    def __init__(
        self, feature: _FakeFeature, update_error: Exception | None = None
    ) -> None:
        self.features = {"led": feature}
        self.update_error = update_error
        self.update_calls = 0
        self.disconnect_calls = 0
        self.config = object()

    async def update(self) -> None:
        self.update_calls += 1
        if self.update_error is not None:
            raise self.update_error
        return None

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        return None


def reset_runtime_state() -> None:
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime_context.auth.container_id = ""
    runtime_context.auth.internal_token = ""
    runtime_context.process_state.background_tasks.clear()
    kasa_client_module._DEVICE_CONFIG_CACHE.clear()


def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for background delivery to complete.")


def test_config_apply_sends_tp_link_telemetry_and_event(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(
        *, host: str, username=None, password=None
    ) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(
        config_module.telemetry_client, "core_base_url", mock_core.base_url
    )
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(
        config_module, "start_device_poll_task", lambda **kwargs: _DummyTask()
    )

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        response = client.post("/config", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["config_id"] == "plug-1"

        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        telemetry_request = assert_telemetry_sent(mock_core, device_id="plug-1")
        event_request = assert_event_sent(
            mock_core,
            device_id="plug-1",
            config_id="plug-1",
            event_type="device.configured",
        )

        telemetry_headers = {
            key.lower(): value for key, value in telemetry_request.headers.items()
        }
        event_headers = {
            key.lower(): value for key, value in event_request.headers.items()
        }

        assert telemetry_headers["x-container-id"] == "runtime-123"
        assert telemetry_headers["x-piphi-integration-token"] == "secret-token"
        assert event_headers["x-container-id"] == "runtime-123"
        assert event_headers["x-piphi-integration-token"] == "secret-token"
        assert telemetry_request.json_body["device_id"] == "plug-1"
        assert telemetry_request.json_body["metrics"]["current_power_w"] == 8.2
        assert telemetry_request.json_body["metrics"]["switch"] is True
        assert telemetry_request.json_body["metrics"]["energy_power"] == 8.2
        assert telemetry_request.json_body["metrics"]["energy_today"] == 0.12
        assert telemetry_request.json_body["metrics"]["energy_this_month"] == 1.34
        assert telemetry_request.json_body["units"]["current_power_w"] == "W"
        assert (
            event_request.json_body.get("event_type")
            or event_request.json_body.get("type")
        ) == "device.configured"


def test_config_sync_replaces_tp_link_device_and_uses_testkit_snapshot(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(
        *, host: str, username=None, password=None
    ) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(
        config_module.telemetry_client, "core_base_url", mock_core.base_url
    )
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(
        config_module, "start_device_poll_task", lambda **kwargs: _DummyTask()
    )

    old_payload = build_config_payload(
        config_id="plug-old",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    new_payload = build_config_payload(
        config_id="plug-new",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.228",
            "alias": "Lamp Plug",
        },
    )
    snapshot = build_config_snapshot(
        configs=[new_payload],
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        generation=6,
    )
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        first_response = client.post("/config", json=old_payload, headers=headers)
        assert first_response.status_code == 200
        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        mock_core.reset()

        sync_response = client.post("/config/sync", json=snapshot, headers=headers)
        assert sync_response.status_code == 200
        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 2)

        sync_json = sync_response.json()
        assert sync_json["applied"] == ["plug-new"]
        assert sync_json["removed"] == ["plug-old"]
        assert sync_json["active_config_ids"] == ["plug-new"]
        assert sync_json["generation"] == 6

        telemetry_request = assert_telemetry_sent(mock_core, device_id="plug-new")
        configured_event = assert_event_sent(
            mock_core,
            device_id="plug-new",
            config_id="plug-new",
            event_type="device.configured",
        )
        deconfigured_event = assert_event_sent(
            mock_core,
            device_id="plug-old",
            config_id="plug-old",
            event_type="device.deconfigured",
        )

        assert telemetry_request.json_body["metrics"]["current_power_w"] == 8.2
        assert (
            configured_event.json_body.get("event_type")
            or configured_event.json_body.get("type")
        ) == "device.configured"
        assert (
            deconfigured_event.json_body.get("event_type")
            or deconfigured_event.json_body.get("type")
        ) == "device.deconfigured"


def test_config_sync_keeps_duplicate_physical_device_ids_distinct(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(
        *, host: str, username=None, password=None
    ) -> dict[str, object]:
        is_bulb = host == "10.0.0.136"
        return {
            "is_on": is_bulb,
            "device_type": "bulb" if is_bulb else "plug",
            "model": "KL110" if is_bulb else "KP115",
            "signal_strength": -41 if is_bulb else -48,
            "current_power_w": 5.0 if is_bulb else 1.2,
        }

    monkeypatch.setattr(
        config_module.telemetry_client, "core_base_url", mock_core.base_url
    )
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(
        config_module, "start_device_poll_task", lambda **kwargs: _DummyTask()
    )

    configs = [
        {
            "id": "shared-kasa-device-id",
            "config_id": "bulb-config",
            "container_id": "runtime-123",
            "integration_id": "piphi-network-tp-link",
            "host": "10.0.0.136",
            "alias": "Smart Bulb",
        },
        {
            "id": "shared-kasa-device-id",
            "config_id": "plug-config",
            "container_id": "runtime-123",
            "integration_id": "piphi-network-tp-link",
            "host": "10.0.0.227",
            "alias": "KP115 Plug",
        },
    ]
    snapshot = {
        "container_id": "runtime-123",
        "integration_id": "piphi-network-tp-link",
        "generation": 7,
        "configs": configs,
    }
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        response = client.post("/config/sync", json=snapshot, headers=headers)
        assert response.status_code == 200

        response_json = response.json()
        assert response_json["applied"] == ["bulb-config", "plug-config"]
        assert response_json["active_config_ids"] == ["bulb-config", "plug-config"]
        assert registry.ids() == ["bulb-config", "plug-config"]
        assert (
            registry.get("bulb-config")["physical_device_id"] == "shared-kasa-device-id"
        )
        assert (
            registry.get("plug-config")["physical_device_id"] == "shared-kasa-device-id"
        )
        assert registry.get("bulb-config")["host"] == "10.0.0.136"
        assert registry.get("plug-config")["host"] == "10.0.0.227"
        assert registry.get("shared-kasa-device-id") is None

        wait_for(lambda: len(mock_core.telemetry_requests) >= 2)
        assert_telemetry_sent(mock_core, device_id="bulb-config")
        assert_telemetry_sent(mock_core, device_id="plug-config")


def test_config_sync_accepts_masked_secret_placeholders(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(
        *, host: str, username=None, password=None
    ) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP115",
            "signal_strength": -48,
        }

    monkeypatch.setattr(
        config_module.telemetry_client, "core_base_url", mock_core.base_url
    )
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(
        config_module, "start_device_poll_task", lambda **kwargs: _DummyTask()
    )

    snapshot = {
        "container_id": "runtime-123",
        "integration_id": "piphi-network-tp-link",
        "generation": 8,
        "configs": [
            {
                "id": "plug-1",
                "config_id": "plug-1",
                "container_id": "runtime-123",
                "integration_id": "piphi-network-tp-link",
                "host": "10.0.0.227",
                "alias": "KP115 Plug",
                "password": {"__piphi_secret__": True, "masked": True},
            }
        ],
    }
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        response = client.post("/config/sync", json=snapshot, headers=headers)

    assert response.status_code == 200
    assert registry.get("plug-1")["password"] is None


def test_state_route_refreshes_missing_tp_link_snapshot_with_testkit(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(
        *, host: str, username=None, password=None
    ) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(
        config_module.telemetry_client, "core_base_url", mock_core.base_url
    )
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(
        config_module, "start_device_poll_task", lambda **kwargs: _DummyTask()
    )

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload, headers=headers)
        assert config_response.status_code == 200
        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)

        mock_core.reset()
        registry.state_snapshots.clear()

        state_response = client.get("/state")
        assert state_response.status_code == 200
        assert state_response.json()["device_id"] == "plug-1"
        assert state_response.json()["state"]["current_power_w"] == 8.2

        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        telemetry_request = assert_telemetry_sent(mock_core, device_id="plug-1")
        assert telemetry_request.json_body["metrics"]["current_power_w"] == 8.2


def test_deconfigure_sends_tp_link_event_and_removes_entry(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_state(
        *, host: str, username=None, password=None
    ) -> dict[str, object]:
        return {
            "is_on": True,
            "device_type": "plug",
            "model": "KP125M",
            "signal_strength": -42,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        }

    monkeypatch.setattr(
        config_module.telemetry_client, "core_base_url", mock_core.base_url
    )
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", fake_fetch_device_state)
    monkeypatch.setattr(
        config_module, "start_device_poll_task", lambda **kwargs: _DummyTask()
    )

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload, headers=headers)
        assert config_response.status_code == 200
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        mock_core.reset()

        deconfigure_response = client.post(
            "/deconfigure", json={"config": {"id": "plug-1"}}
        )
        assert deconfigure_response.status_code == 200
        assert deconfigure_response.json()["removed"] is True
        assert registry.get("plug-1") is None

        wait_for(lambda: len(mock_core.event_requests) >= 1)
        event_request = assert_event_sent(
            mock_core,
            device_id="plug-1",
            config_id="plug-1",
            event_type="device.deconfigured",
        )
        assert (
            event_request.json_body.get("event_type")
            or event_request.json_body.get("type")
        ) == "device.deconfigured"


def test_state_returns_404_when_no_tp_link_device_is_configured() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/state")

    assert response.status_code == 404
    assert response.json()["detail"] == "No configured device found"


def test_tp_link_state_refresh_requires_and_echoes_request_id(monkeypatch) -> None:
    reset_runtime_state()
    registry.set(
        "plug-1",
        {
            "config_id": "config-1",
            "device_id": "plug-1",
            "host": "192.168.1.25",
        },
    )
    registry.update_state("plug-1", {"is_on": False})

    async def fake_trigger_refresh(device_id: str):
        assert device_id == "plug-1"
        return registry.update_state(device_id, {"is_on": True})

    monkeypatch.setattr(state_module, "trigger_refresh", fake_trigger_refresh)

    with TestClient(app) as client:
        missing_id = client.get("/state?refresh=true")
        refreshed = client.get(
            "/state?refresh=true&refresh_request_id=refresh-123"
        )

    assert missing_id.status_code == 400
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["entries"]["config-1"]["latest_state"]["is_on"] is True
    assert payload["refresh"] == {
        "request_id": "refresh-123",
        "performed": True,
        "status": "refreshed",
        "observed_at": payload["refresh"]["observed_at"],
        "source": "kasa_device",
    }


def test_deconfigure_requires_config_id_for_tp_link() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post("/deconfigure", json={"config": {}})

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing config id"


def test_tp_link_events_route_round_trip() -> None:
    reset_runtime_state()

    event_payload = {
        "event_type": "tp_link.manual.note",
        "source": "test-suite",
        "payload": {"message": "hello"},
    }

    with TestClient(app) as client:
        ingest_response = client.post("/events", json=event_payload)
        list_response = client.get("/events")

    assert ingest_response.status_code == 200
    assert ingest_response.json()["event"]["event_type"] == "tp_link.manual.note"
    assert list_response.status_code == 200
    assert list_response.json()["events"][-1]["event_type"] == "tp_link.manual.note"


def test_tp_link_command_requires_command_name() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post("/command", json={"command": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing command"


def test_tp_link_command_returns_404_without_primary_device() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post("/command", json={"command": "turn_on"})

    assert response.status_code == 404
    assert response.json()["detail"] == "No configured device found"


def test_tp_link_command_runs_device_command_and_returns_refreshed_state(
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def fake_run_command_for_device(
        *, device_id: str, command: str, args: dict[str, object]
    ):
        return {"ok": True, "command": command, "args": args}

    async def fake_trigger_refresh(device_id: str):
        return {"device_id": device_id, "state": {"is_on": True}}

    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )

    monkeypatch.setattr(
        command_module, "run_command_for_device", fake_run_command_for_device
    )
    monkeypatch.setattr(command_module, "trigger_refresh", fake_trigger_refresh)

    with TestClient(app) as client:
        response = client.post(
            "/command",
            json={
                "command": "turn_on",
                "device_id": "plug-1",
                "args": {"transition": 1},
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result"]["command"] == "turn_on"
    assert response.json()["state"]["state"]["is_on"] is True


def test_tp_link_command_replays_idempotency_key_without_repeating_device_effect(
    monkeypatch,
) -> None:
    reset_runtime_state()
    calls = 0

    async def fake_run_command_for_device(
        *, device_id: str, command: str, args: dict[str, object]
    ):
        nonlocal calls
        calls += 1
        return {"ok": True, "command": command, "args": args}

    async def fake_trigger_refresh(device_id: str):
        return {"device_id": device_id, "state": {"is_on": True}}

    registry.set(
        "plug-idempotency-1",
        {
            "config_id": "plug-idempotency-1",
            "device_id": "plug-idempotency-1",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )
    monkeypatch.setattr(
        command_module, "run_command_for_device", fake_run_command_for_device
    )
    monkeypatch.setattr(command_module, "trigger_refresh", fake_trigger_refresh)

    headers = {"X-PiPhi-Idempotency-Key": "tp-link-action-idempotency-1"}
    payload = {
        "command": "turn_on",
        "device_id": "plug-idempotency-1",
    }
    with TestClient(app) as client:
        first = client.post("/command", json=payload, headers=headers)
        replay = client.post("/command", json=payload, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert calls == 1


def test_tp_link_config_apply_still_succeeds_when_initial_refresh_fails(
    mock_core,
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def failing_fetch_device_state(
        *, host: str, username=None, password=None
    ) -> dict[str, object]:
        raise RuntimeError("device unavailable")

    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module, "fetch_device_state", failing_fetch_device_state)
    monkeypatch.setattr(
        config_module, "start_device_poll_task", lambda **kwargs: _DummyTask()
    )

    payload = build_config_payload(
        config_id="plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tp-link",
        extra={
            "host": "10.0.0.227",
            "alias": "Desk Plug",
        },
    )
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        response = client.post("/config", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["config_id"] == "plug-1"
        wait_for(lambda: len(mock_core.event_requests) >= 1)

        configured_event = assert_event_sent(
            mock_core,
            device_id="plug-1",
            config_id="plug-1",
            event_type="device.configured",
        )

    assert registry.get("plug-1") is not None
    assert (
        configured_event.json_body.get("event_type")
        or configured_event.json_body.get("type")
    ) == "device.configured"


@pytest.mark.parametrize("path", ["/ui", "/ui-config"])
def test_tp_link_ui_aliases_return_schema(path: str) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"]["title"] == "TP-Link Kasa Configuration"
    assert "host" in payload["schema"]["properties"]
    assert "alias" in payload["schema"]["properties"]


@pytest.mark.parametrize("field_name", ["host", "alias", "username", "password"])
def test_tp_link_ui_schema_contains_expected_fields(field_name: str) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/ui-config")

    assert response.status_code == 200
    assert field_name in response.json()["schema"]["properties"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/discover"),
        ("get", "/discovery"),
        ("post", "/discover"),
        ("post", "/discovery"),
    ],
)
def test_tp_link_discovery_aliases_return_devices(
    method: str, path: str, monkeypatch
) -> None:
    reset_runtime_state()

    async def fake_discover_devices(username=None, password=None):
        return [{"device_id": "plug-1", "host": "10.0.0.227"}]

    monkeypatch.setattr(discovery_module, "discover_devices", fake_discover_devices)

    with TestClient(app) as client:
        if method == "get":
            response = client.get(path)
        else:
            response = client.post(path, json={"username": "user", "password": "pass"})

    assert response.status_code == 200
    assert response.json()["devices"][0]["device_id"] == "plug-1"


def test_tp_link_discovery_post_passes_credentials(monkeypatch) -> None:
    reset_runtime_state()
    observed: dict[str, object] = {}

    async def fake_discover_devices(username=None, password=None):
        observed["username"] = username
        observed["password"] = password
        return [{"device_id": "plug-1", "host": "10.0.0.227"}]

    monkeypatch.setattr(discovery_module, "discover_devices", fake_discover_devices)

    with TestClient(app) as client:
        response = client.post(
            "/discover", json={"username": "user", "password": "pass"}
        )

    assert response.status_code == 200
    assert observed == {"username": "user", "password": "pass"}


def test_tp_link_discovery_post_passes_host_hint(monkeypatch) -> None:
    reset_runtime_state()
    observed: dict[str, object] = {}

    async def fake_discover_devices(username=None, password=None, host=None):
        observed["host"] = host
        observed["username"] = username
        observed["password"] = password
        return [{"device_id": "plug-1", "host": host}]

    monkeypatch.setattr(discovery_module, "discover_devices", fake_discover_devices)

    with TestClient(app) as client:
        response = client.post(
            "/discover",
            json={"host": " 10.0.0.227 ", "username": "user", "password": "pass"},
        )

    assert response.status_code == 200
    assert observed == {"host": "10.0.0.227", "username": "user", "password": "pass"}
    assert response.json()["devices"][0]["host"] == "10.0.0.227"


def test_tp_link_discovery_returns_500_on_exception(monkeypatch) -> None:
    reset_runtime_state()

    async def failing_discover_devices(username=None, password=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(discovery_module, "discover_devices", failing_discover_devices)

    with TestClient(app) as client:
        response = client.get("/discover")

    assert response.status_code == 500
    assert "Discovery failed: boom" in response.json()["detail"]


def test_tp_link_targeted_discovery_uses_host_hint(monkeypatch) -> None:
    reset_runtime_state()
    observed: dict[str, object] = {}
    feature = _FakeFeature()
    device = _FakeKasaDevice(feature)

    async def fake_resolve_device(*, host: str, username=None, password=None):
        observed["host"] = host
        observed["username"] = username
        observed["password"] = password
        return device

    async def failing_broadcast_discover(**kwargs):
        raise AssertionError("broadcast discovery should not run when host is provided")

    monkeypatch.setattr(kasa_client_module, "_resolve_device", fake_resolve_device)
    monkeypatch.setattr(
        kasa_client_module.Discover, "discover", failing_broadcast_discover
    )

    devices = asyncio.run(
        kasa_client_module.discover_devices(
            host="10.0.0.227",
            username="user",
            password="pass",
        )
    )

    assert observed == {"host": "10.0.0.227", "username": "user", "password": "pass"}
    assert devices[0]["host"] == "192.168.1.25"
    assert devices[0]["name"] == "Desk Plug"
    assert device.disconnect_calls == 1


def test_tp_link_fetch_device_state_disconnects_after_serializing(monkeypatch) -> None:
    reset_runtime_state()
    device = _FakeKasaDevice(_FakeFeature())

    async def fake_resolve_device(*, host: str, username=None, password=None):
        return device

    monkeypatch.setattr(kasa_client_module, "_resolve_device", fake_resolve_device)

    state = asyncio.run(kasa_client_module.fetch_device_state(host="10.0.0.227"))

    assert state["host"] == "192.168.1.25"
    assert device.update_calls == 1
    assert device.disconnect_calls == 1


def test_tp_link_fetch_device_state_observes_external_power_change(monkeypatch) -> None:
    reset_runtime_state()

    class ExternallyChangedDevice(_FakeKasaDevice):
        is_on = False

        async def update(self) -> None:
            await super().update()
            self.is_on = True

    device = ExternallyChangedDevice(_FakeFeature())

    async def fake_resolve_device(*, host: str, username=None, password=None):
        return device

    monkeypatch.setattr(kasa_client_module, "_resolve_device", fake_resolve_device)

    state = asyncio.run(kasa_client_module.fetch_device_state(host="10.0.0.227"))

    assert state["is_on"] is True
    assert device.update_calls == 1
    assert device.disconnect_calls == 1


def test_tp_link_resolve_device_prefers_direct_connect_for_targeted_host(
    monkeypatch,
) -> None:
    reset_runtime_state()
    observed_host: str | None = None
    observed_timeout: int | None = None
    observed_username: str | None = None
    observed_password: str | None = None
    device = _FakeKasaDevice(_FakeFeature())

    async def fake_try_connect_all(host, *, timeout=None, credentials=None, **kwargs):
        nonlocal observed_host, observed_timeout, observed_username, observed_password
        observed_host = host
        observed_timeout = timeout
        observed_username = credentials.username if credentials else None
        observed_password = credentials.password if credentials else None
        return device

    async def failing_discover_single(*args, **kwargs):
        raise AssertionError(
            "discover_single should not run when direct connect succeeds"
        )

    monkeypatch.setattr(
        kasa_client_module.Discover, "try_connect_all", fake_try_connect_all
    )
    monkeypatch.setattr(
        kasa_client_module.Discover, "discover_single", failing_discover_single
    )

    resolved = asyncio.run(
        kasa_client_module._resolve_device(
            host="10.0.0.227",
            username="user@example.com",
            password="secret-pass",
        )
    )

    assert resolved is device
    assert observed_host == "10.0.0.227"
    assert observed_timeout == kasa_client_module._DIRECT_CONNECT_TIMEOUT
    assert observed_username == "user@example.com"
    assert observed_password == "secret-pass"


def test_tp_link_resolve_device_uses_cached_config_after_success(monkeypatch) -> None:
    reset_runtime_state()
    first_device = _FakeKasaDevice(_FakeFeature())
    cached_config = first_device.config
    second_device = _FakeKasaDevice(_FakeFeature())
    try_connect_all_calls = 0
    seen_cached_config = None

    async def fake_try_connect_all(host, *, timeout=None, credentials=None, **kwargs):
        nonlocal try_connect_all_calls
        try_connect_all_calls += 1
        return first_device

    async def fake_device_connect(*, config):
        nonlocal seen_cached_config
        seen_cached_config = config
        return second_device

    async def failing_discover_single(*args, **kwargs):
        raise AssertionError(
            "discover_single should not run when direct connect succeeds"
        )

    monkeypatch.setattr(
        kasa_client_module.Discover, "try_connect_all", fake_try_connect_all
    )
    monkeypatch.setattr(kasa_client_module.Device, "connect", fake_device_connect)
    monkeypatch.setattr(
        kasa_client_module.Discover, "discover_single", failing_discover_single
    )

    first_resolved = asyncio.run(kasa_client_module._resolve_device(host="10.0.0.227"))
    second_resolved = asyncio.run(kasa_client_module._resolve_device(host="10.0.0.227"))

    assert first_resolved is first_device
    assert second_resolved is second_device
    assert try_connect_all_calls == 1
    assert seen_cached_config is cached_config


def test_tp_link_resolve_device_disconnects_when_initial_update_fails(
    monkeypatch,
) -> None:
    reset_runtime_state()
    device = _FakeKasaDevice(_FakeFeature(), update_error=RuntimeError("update failed"))

    async def fake_try_connect_all(*args, **kwargs):
        return None

    async def fake_discover_single(*args, **kwargs):
        return device

    monkeypatch.setattr(
        kasa_client_module.Discover, "try_connect_all", fake_try_connect_all
    )
    monkeypatch.setattr(
        kasa_client_module.Discover, "discover_single", fake_discover_single
    )

    with pytest.raises(RuntimeError, match="update failed"):
        asyncio.run(kasa_client_module.fetch_device_state(host="10.0.0.227"))

    assert device.disconnect_calls == 1


def test_tp_link_broadcast_discovery_disconnects_failed_devices(monkeypatch) -> None:
    reset_runtime_state()
    device = _FakeKasaDevice(_FakeFeature())

    async def fake_broadcast_discover(**kwargs):
        return {"10.0.0.227": device}

    monkeypatch.setattr(
        kasa_client_module.Discover, "discover", fake_broadcast_discover
    )
    monkeypatch.setattr(
        kasa_client_module,
        "_serialize_device",
        lambda _device: (_ for _ in ()).throw(RuntimeError("read failed")),
    )

    with pytest.raises(
        RuntimeError, match="Discovered devices, but none could be read"
    ):
        asyncio.run(kasa_client_module.discover_devices())

    assert device.disconnect_calls == 1


def test_tp_link_discovery_uses_each_detected_lan_broadcast(monkeypatch) -> None:
    reset_runtime_state()
    device = _FakeKasaDevice(_FakeFeature())
    observed_targets: list[str] = []

    monkeypatch.delenv(kasa_client_module._DISCOVERY_TARGETS_ENV, raising=False)
    monkeypatch.setattr(
        kasa_client_module,
        "_linux_interface_networks",
        lambda: [
            kasa_client_module.ipaddress.ip_network("10.0.0.0/24"),
            kasa_client_module.ipaddress.ip_network("192.168.50.0/24"),
        ],
    )

    async def fake_broadcast_discover(**kwargs):
        observed_targets.append(kwargs["target"])
        if kwargs["target"] == "10.0.0.255":
            return {"10.0.0.227": device}
        return {}

    monkeypatch.setattr(
        kasa_client_module.Discover, "discover", fake_broadcast_discover
    )

    devices = asyncio.run(kasa_client_module.discover_devices())

    assert observed_targets == ["10.0.0.255", "192.168.50.255"]
    assert devices[0]["host"] == "192.168.1.25"
    assert device.update_calls == 1
    assert device.disconnect_calls == 1


def test_tp_link_discovery_target_override_is_deduplicated(monkeypatch) -> None:
    monkeypatch.setenv(
        kasa_client_module._DISCOVERY_TARGETS_ENV,
        "10.0.0.255, 192.168.1.255,10.0.0.255",
    )

    assert kasa_client_module._discovery_targets() == [
        "10.0.0.255",
        "192.168.1.255",
    ]


def test_tp_link_broadcast_discovery_reports_host_hint_on_scan_failure(
    monkeypatch,
) -> None:
    reset_runtime_state()

    async def failing_broadcast_discover(**kwargs):
        raise RuntimeError("No time zone found with key EST")

    monkeypatch.setattr(
        kasa_client_module.Discover, "discover", failing_broadcast_discover
    )

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(kasa_client_module.discover_devices())

    message = str(exc_info.value)
    assert "Network scan failed" in message
    assert "device IP address or hostname" in message
    assert "No time zone found with key EST" in message


def test_tp_link_events_list_is_empty_by_default() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/events")

    assert response.status_code == 200
    assert response.json()["events"] == []


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("tp_link.manual.note", {"message": "hello"}),
        ("tp_link.energy.warning", {"current_power_w": 99.1}),
        ("tp_link.device.ping", {"host": "10.0.0.227"}),
    ],
)
def test_tp_link_events_route_round_trip_variants(
    event_type: str, payload: dict[str, object]
) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        ingest_response = client.post(
            "/events",
            json={
                "event_type": event_type,
                "source": "test-suite",
                "payload": payload,
            },
        )
        list_response = client.get("/events")

    assert ingest_response.status_code == 200
    assert ingest_response.json()["event"]["event_type"] == event_type
    assert list_response.status_code == 200
    assert list_response.json()["events"][-1]["payload"] == payload


@pytest.mark.parametrize("path", ["/health", "/diagnostics"])
def test_tp_link_health_routes_work_without_devices(path: str) -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200


def test_tp_link_health_reports_configured_and_state_counts() -> None:
    reset_runtime_state()
    registry.set("plug-1", {"config_id": "plug-1", "device_id": "plug-1"})
    registry.update_state("plug-1", {"current_power_w": 8.2})

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["metadata"]["devices_configured"] == 1
    assert response.json()["metadata"]["devices_with_state"] == 1


def test_tp_link_diagnostics_reports_device_ids() -> None:
    reset_runtime_state()
    registry.set("plug-1", {"config_id": "plug-1", "device_id": "plug-1"})
    registry.update_state("plug-1", {"current_power_w": 8.2})

    with TestClient(app) as client:
        response = client.get("/diagnostics")

    assert response.status_code == 200
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["configured_device_ids"] == ["plug-1"]
    assert diagnostics["devices_with_state"] == ["plug-1"]


def test_tp_link_entities_route_returns_device_specific_commands() -> None:
    reset_runtime_state()
    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "alias": "Kitchen Plug",
            "host": "192.168.1.25",
        },
    )
    registry.update_state(
        "plug-1",
        {
            "capabilities": [
                "switch",
                "power",
                "energy_power",
                "energy_today",
                "energy_this_month",
            ],
            "device_type": "DeviceType.Plug",
            "model": "KP115",
            "is_on": True,
            "current_power_w": 8.2,
            "today_kwh": 0.12,
            "month_kwh": 1.34,
        },
    )

    with TestClient(app) as client:
        response = client.get("/entities")

    assert response.status_code == 200
    payload = response.json()
    assert "entities" in payload
    assert "capabilities" in payload
    assert "commands" in payload
    assert len(payload["entities"]) == 1
    entity = payload["entities"][0]
    assert entity["device_class"] == "plug"
    assert entity["entity_type"] == "switch"
    assert [command["id"] for command in entity["available_commands"]] == [
        "toggle",
        "turn_on",
        "turn_off",
        "read_energy",
        "refresh",
    ]
    assert entity["available_commands"][0]["label"] == "Toggle"
    assert entity["available_commands"][3]["label"] == "Refresh Energy"


def test_tp_link_manifest_route_returns_identity_fields() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/manifest.json")

    assert response.status_code == 200
    assert response.json()["id"]
    assert response.json()["name"]
    assert response.json()["version"]


def test_tp_link_manifest_maps_action_capabilities_to_commands() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/manifest.json")

    assert response.status_code == 200
    manifest = response.json()
    action_capabilities = {
        capability_id
        for capability_id, capability in manifest["capabilities"].items()
        if capability.get("kind") == "action"
    }

    assert action_capabilities <= set(manifest["commands"])
    assert "dynamic_feature" in manifest["commands"]


def test_dynamic_feature_command_sets_writable_feature(monkeypatch) -> None:
    feature = _FakeFeature()
    device = _FakeKasaDevice(feature)

    async def fake_resolve_device(*, host: str, username=None, password=None):
        return device

    monkeypatch.setattr(kasa_client_module, "_resolve_device", fake_resolve_device)

    asyncio.run(
        kasa_client_module.execute_device_command(
            host="192.168.1.25",
            command="dynamic_feature",
            args={"feature_id": "led", "value": False},
        )
    )

    assert feature.value is False
    assert device.disconnect_calls == 1


@pytest.mark.parametrize(
    ("command", "feature_id", "args", "expected"),
    [
        ("set_brightness", "brightness", {"brightness": 42}, 42),
        ("set_color_temperature", "color_temperature", {"kelvin": 3000}, 3000),
    ],
)
def test_named_light_command_arguments_match_the_entity_contract(
    monkeypatch, command: str, feature_id: str, args: dict[str, int], expected: int
) -> None:
    feature = _FakeFeature()
    device = _FakeKasaDevice(feature)
    device.features = {feature_id: feature}

    async def fake_resolve_device(*, host: str, username=None, password=None):
        return device

    monkeypatch.setattr(kasa_client_module, "_resolve_device", fake_resolve_device)

    asyncio.run(
        kasa_client_module.execute_device_command(
            host="192.168.1.25",
            command=command,
            args=args,
        )
    )

    assert feature.value == expected
    assert device.disconnect_calls == 1


def test_supported_light_commands_advertise_their_canonical_argument_names() -> None:
    device = _FakeKasaDevice(_FakeFeature())
    commands = kasa_client_module._build_supported_commands(
        device,
        {
            "brightness": {"id": "brightness", "writable": True},
            "color_temperature": {
                "id": "color_temperature",
                "writable": True,
            },
        },
    )
    args_by_command = {command["id"]: command["args"] for command in commands}

    assert args_by_command["set_brightness"] == ["brightness"]
    assert args_by_command["set_color_temperature"] == ["kelvin"]


def test_tp_link_state_returns_404_for_unknown_explicit_device() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.get("/state", params={"device_id": "missing-device"})

    assert response.status_code == 404
    assert "No state available" in response.json()["detail"]


def test_tp_link_deconfigure_returns_false_when_device_missing() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post(
            "/deconfigure", json={"config": {"id": "missing-device"}}
        )

    assert response.status_code == 200
    assert response.json()["removed"] is False


def test_tp_link_command_uses_primary_device_when_device_id_missing(
    monkeypatch,
) -> None:
    reset_runtime_state()
    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )

    observed: dict[str, object] = {}

    async def fake_run_command_for_device(
        *, device_id: str, command: str, args: dict[str, object]
    ):
        observed["device_id"] = device_id
        observed["command"] = command
        return {"ok": True}

    async def fake_trigger_refresh(device_id: str):
        return {"device_id": device_id, "state": {"is_on": True}}

    monkeypatch.setattr(
        command_module, "run_command_for_device", fake_run_command_for_device
    )
    monkeypatch.setattr(command_module, "trigger_refresh", fake_trigger_refresh)

    with TestClient(app) as client:
        response = client.post("/command", json={"command": "turn_on"})

    assert response.status_code == 200
    assert observed["device_id"] == "plug-1"
    assert observed["command"] == "turn_on"


def test_tp_link_command_prefers_target_config_id_over_payload_device_id(
    monkeypatch,
) -> None:
    reset_runtime_state()
    registry.set(
        "bulb-config",
        {
            "config_id": "bulb-config",
            "device_id": "bulb-config",
            "physical_device_id": "shared-kasa-device-id",
            "container_id": "runtime-123",
            "host": "10.0.0.136",
        },
    )
    registry.set(
        "plug-config",
        {
            "config_id": "plug-config",
            "device_id": "plug-config",
            "physical_device_id": "shared-kasa-device-id",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )

    observed: dict[str, object] = {}

    async def fake_run_command_for_device(
        *, device_id: str, command: str, args: dict[str, object]
    ):
        observed["device_id"] = device_id
        observed["command"] = command
        return {"ok": True}

    async def fake_trigger_refresh(device_id: str):
        return {"device_id": device_id, "state": {"is_on": True}}

    monkeypatch.setattr(
        command_module, "run_command_for_device", fake_run_command_for_device
    )
    monkeypatch.setattr(command_module, "trigger_refresh", fake_trigger_refresh)

    with TestClient(app) as client:
        response = client.post(
            "/command",
            json={
                "command": "turn_on",
                "device_id": "shared-kasa-device-id",
                "target": {"config_id": "bulb-config"},
            },
        )

    assert response.status_code == 200
    assert observed["device_id"] == "bulb-config"
    assert observed["command"] == "turn_on"


def test_tp_link_command_propagates_device_failure(monkeypatch) -> None:
    reset_runtime_state()
    registry.set(
        "plug-1",
        {
            "config_id": "plug-1",
            "device_id": "plug-1",
            "container_id": "runtime-123",
            "host": "10.0.0.227",
        },
    )

    from fastapi import HTTPException

    async def failing_run_command_for_device(
        *, device_id: str, command: str, args: dict[str, object]
    ):
        raise HTTPException(status_code=400, detail="Command failed")

    monkeypatch.setattr(
        command_module, "run_command_for_device", failing_run_command_for_device
    )

    with TestClient(app) as client:
        response = client.post(
            "/command", json={"command": "turn_on", "device_id": "plug-1"}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Command failed"
