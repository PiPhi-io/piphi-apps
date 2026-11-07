from __future__ import annotations

import importlib
import math
import time
from copy import deepcopy

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from piphi_runtime_testkit_python import (
    assert_event_sent,
    assert_telemetry_sent,
    build_runtime_headers,
)

from piphi_network_thinqconnect.app import app
from piphi_network_thinqconnect.lib.normalization import build_command_catalog
from piphi_network_thinqconnect.lib.store import registry, runtime_context

config_module = importlib.import_module("piphi_network_thinqconnect.contract.config.routes")
command_module = importlib.import_module("piphi_network_thinqconnect.contract.command.router")
discovery_module = importlib.import_module("piphi_network_thinqconnect.contract.discovery.discovery")
state_module = importlib.import_module("piphi_network_thinqconnect.contract.state.router")


class _DummyTask:
    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        return None


def reset_runtime_state() -> None:
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime_context.auth.container_id = ""
    runtime_context.auth.internal_token = ""
    runtime_context.process_state.background_tasks.clear()


def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for background delivery to complete.")


def _ac_snapshot() -> dict:
    return {
        "device": {
            "deviceId": "device-ac-1",
            "deviceType": "DEVICE_AIR_CONDITIONER",
            "deviceName": "Living Room AC",
            "modelName": "DualCool",
        },
        "status": {
            "current_temperature_c": 23.5,
            "target_temperature_c": 24.0,
            "humidity": 45,
            "filter_remain_percent": 74,
            "operation": "OFF",
            "mode": "COOL",
            "online": True,
        },
        "profile": {
            "main": {
                "resources": ["temperature", "humidity", "operation"],
            }
        },
        "available_controls": [
            {
                "method": "set_operation",
                "parameters": [
                    {"name": "operation", "options": ["ON", "OFF"]},
                ],
            },
            {
                "method": "set_mode",
                "parameters": [
                    {"name": "mode", "options": ["COOL", "HEAT", "DRY"]},
                ],
            },
            {
                "method": "set_target_temperature",
                "parameters": [
                    {
                        "name": "temperature",
                        "type": "number",
                        "min": 16,
                        "max": 30,
                        "unit": "°C",
                    }
                ],
            },
        ],
        "client_id": "generated-client-id",
    }


def _fridge_snapshot() -> dict:
    return {
        "device": {
            "deviceId": "fridge-1",
            "deviceType": "DEVICE_REFRIGERATOR",
            "deviceName": "Kitchen Fridge",
            "modelName": "LFXS26973S",
        },
        "status": {
            "door_state": "CLOSED",
            "current_state": "IDLE",
            "fresh_air_filter_remain_percent": 81,
            "target_temperature_c": 3,
            "online": True,
        },
        "profile": {},
        "available_controls": [
            {
                "method": "set_target_temperature",
                "parameters": [
                    {
                        "name": "temperature",
                        "type": "number",
                        "min": 1,
                        "max": 7,
                        "unit": "°C",
                    }
                ],
            },
            {
                "method": "set_express_mode",
                "parameters": [
                    {"name": "express_mode", "options": ["ON", "OFF"]},
                ],
            },
            {
                "method": "set_power_save",
                "parameters": [
                    {"name": "power_save", "options": ["ON", "OFF"]},
                ],
            },
        ],
        "client_id": "generated-client-id-fridge",
    }


def test_discovery_returns_mixed_thinq_devices(monkeypatch) -> None:
    reset_runtime_state()

    async def fake_discover_devices(**_kwargs):
        return [
            {
                "id": "device-ac-1",
                "device_id": "device-ac-1",
                "device_name": "Living Room AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
            },
            {
                "id": "fridge-1",
                "device_id": "fridge-1",
                "device_name": "Kitchen Fridge",
                "device_type": "DEVICE_REFRIGERATOR",
            },
        ]

    monkeypatch.setattr(discovery_module.thinq_client, "discover_devices", fake_discover_devices)

    with TestClient(app) as client:
        response = client.post(
            "/discover",
            json={
                "access_token": "token-1",
                "country_code": "US",
                "client_id": "client-1",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["devices"]) == 2
    assert payload["devices"][0]["device_type"] == "DEVICE_AIR_CONDITIONER"
    assert payload["devices"][1]["device_type"] == "DEVICE_REFRIGERATOR"


def test_runtime_contract_declares_automation_endpoints() -> None:
    with TestClient(app) as client:
        response = client.get("/contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["integration_id"] == "lg-thinq-connect-api"
    assert payload["endpoints"] == {
        "health": "/health",
        "entities": "/entities",
        "events": "/events",
        "command": "/command",
        "state": "/state",
        "config": "/config",
        "config_sync": "/configs/sync",
    }
    assert set(payload["required"]) == {
        "health",
        "entities",
        "events",
        "command",
        "state",
        "config",
        "config_sync",
    }


def test_discovery_simulation_needs_no_account_credentials() -> None:
    reset_runtime_state()

    with TestClient(app) as client:
        response = client.post(
            "/discover",
            json={"simulation_mode": True},
        )

    assert response.status_code == 200
    devices = response.json()["devices"]
    assert [device["device_id"] for device in devices] == [
        "sim-thinq-washer",
        "sim-thinq-fridge",
        "sim-thinq-ac",
    ]


def test_config_apply_sends_telemetry_and_event(mock_core, monkeypatch) -> None:
    reset_runtime_state()
    poll_task_start_entries = []

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    def fake_start_device_poll_task(*, device_id):
        poll_task_start_entries.append(registry.get(device_id))
        return _DummyTask()

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module, "start_device_poll_task", fake_start_device_poll_task)

    headers = build_runtime_headers(container_id="runtime-456", internal_token="secret-token")

    with TestClient(app) as client:
        response = client.post(
            "/config",
            json={
                "id": "cfg-ac-1",
                "config_id": "cfg-ac-1",
                "device_id": "device-ac-1",
                "device_name": "Living Room AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
                "alias": "Main AC",
            },
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["config_id"] == "cfg-ac-1"

        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 1)

    telemetry_request = assert_telemetry_sent(mock_core, device_id="device-ac-1")
    event_request = assert_event_sent(
        mock_core,
        device_id="device-ac-1",
        config_id="cfg-ac-1",
        event_type="device.configured",
    )
    telemetry_headers = {key.lower(): value for key, value in telemetry_request.headers.items()}
    event_headers = {key.lower(): value for key, value in event_request.headers.items()}

    assert telemetry_headers["x-container-id"] == "runtime-456"
    assert telemetry_headers["x-piphi-integration-token"] == "secret-token"
    assert event_headers["x-container-id"] == "runtime-456"
    assert event_headers["x-piphi-integration-token"] == "secret-token"
    assert telemetry_request.json_body["metrics"]["current_temperature_c"] == 23.5
    assert telemetry_request.json_body["metrics"]["temperature"] == 23.5
    assert telemetry_request.json_body["metrics"]["target_temperature"] == 24.0
    assert telemetry_request.json_body["metrics"]["filter_life"] == 74
    assert telemetry_request.json_body["metrics"]["switch"] is False
    assert telemetry_request.json_body["units"]["temperature"] == "°C"
    assert telemetry_request.json_body["units"]["current_temperature_c"] == "°C"
    assert len(poll_task_start_entries) == 1
    assert poll_task_start_entries[0] is not None
    assert registry.get("cfg-ac-1")["task"].done()


def test_config_apply_keeps_real_polling_task_alive_and_cleans_up(
    mock_core, monkeypatch
) -> None:
    reset_runtime_state()

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module, "_poll_interval", lambda _entry: 0.02)
    headers = build_runtime_headers(container_id="runtime-456", internal_token="secret-token")
    payload = {
        "id": "cfg-ac-polling",
        "config_id": "cfg-ac-polling",
        "device_id": "device-ac-polling",
        "device_name": "Polling AC",
        "device_type": "DEVICE_AIR_CONDITIONER",
        "access_token": "pat-1",
        "country_code": "US",
    }

    with TestClient(app) as client:
        first = client.post("/config", json=payload, headers=headers)
        assert first.status_code == 200
        first_task = registry.get("cfg-ac-polling")["task"]
        assert not first_task.done()
        wait_for(lambda: len(mock_core.telemetry_requests) >= 2)

        second = client.post("/config", json=payload, headers=headers)
        assert second.status_code == 200
        second_task = registry.get("cfg-ac-polling")["task"]
        assert second_task is not first_task
        wait_for(first_task.done)
        assert first_task.cancelled()
        assert not second_task.done()

        removed = client.post(
            "/deconfigure",
            json={"config": {"id": "cfg-ac-polling"}},
            headers=headers,
        )
        assert removed.status_code == 200
        wait_for(second_task.done)
        assert second_task.cancelled()

        shutdown_payload = {**payload, "id": "cfg-shutdown", "config_id": "cfg-shutdown"}
        assert client.post("/config", json=shutdown_payload, headers=headers).status_code == 200
        shutdown_task = registry.get("cfg-shutdown")["task"]
        assert not shutdown_task.done()

    assert shutdown_task.done()
    assert shutdown_task.cancelled()
    assert len(mock_core.telemetry_requests) >= 2
    telemetry_headers = {
        key.lower(): value for key, value in mock_core.telemetry_requests[-1].headers.items()
    }
    assert telemetry_headers["x-container-id"] == "runtime-456"
    assert telemetry_headers["x-piphi-integration-token"] == "secret-token"


def test_config_apply_rolls_back_when_poll_task_cannot_start(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(
        config_module,
        "start_device_poll_task",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("poll task failed")),
    )
    headers = build_runtime_headers(container_id="runtime-456", internal_token="secret-token")

    with TestClient(app) as client, pytest.raises(RuntimeError, match="poll task failed"):
        client.post(
            "/config",
            json={
                "id": "cfg-ac-rollback",
                "config_id": "cfg-ac-rollback",
                "device_id": "device-ac-rollback",
                "device_name": "Rollback AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )

    assert registry.get("cfg-ac-rollback") is None


def test_config_apply_awaits_poll_task_when_registry_entry_disappears(monkeypatch) -> None:
    reset_runtime_state()
    original_start = config_module.start_device_poll_task
    captured_tasks = []

    def start_then_remove(*, device_id):
        task = original_start(device_id=device_id)
        captured_tasks.append(task)
        registry.remove(device_id)
        return task

    monkeypatch.setattr(config_module, "start_device_poll_task", start_then_remove)
    headers = build_runtime_headers(container_id="runtime-456", internal_token="secret-token")

    with TestClient(app) as client, pytest.raises(RuntimeError, match="disappeared"):
        client.post(
            "/config",
            json={
                "id": "cfg-ac-disappeared",
                "config_id": "cfg-ac-disappeared",
                "device_id": "device-ac-disappeared",
                "device_name": "Disappearing AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )

    assert registry.get("cfg-ac-disappeared") is None
    assert len(captured_tasks) == 1
    assert captured_tasks[0].done()
    assert captured_tasks[0].cancelled()


def test_config_apply_cleans_up_poll_task_when_initial_refresh_crashes(monkeypatch) -> None:
    reset_runtime_state()
    captured_tasks = []
    original_start = config_module.start_device_poll_task

    def capture_task(*, device_id):
        task = original_start(device_id=device_id)
        captured_tasks.append(task)
        return task

    async def crash_refresh(_device_id):
        raise RuntimeError("unexpected refresh failure")

    monkeypatch.setattr(config_module, "start_device_poll_task", capture_task)
    monkeypatch.setattr(config_module, "trigger_refresh", crash_refresh)
    headers = build_runtime_headers(container_id="runtime-456", internal_token="secret-token")

    with TestClient(app) as client, pytest.raises(RuntimeError, match="unexpected refresh failure"):
        client.post(
            "/config",
            json={
                "id": "cfg-ac-refresh-crash",
                "config_id": "cfg-ac-refresh-crash",
                "device_id": "device-ac-refresh-crash",
                "device_name": "Crashing AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )

    assert registry.get("cfg-ac-refresh-crash") is None
    assert len(captured_tasks) == 1
    assert captured_tasks[0].done()
    assert captured_tasks[0].cancelled()


def test_runtime_auth_bootstrap_rejects_takeover_and_protects_deconfigure(
    monkeypatch,
) -> None:
    reset_runtime_state()
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())
    legitimate_headers = build_runtime_headers(
        container_id="runtime-owner",
        internal_token="owner-token",
    )
    attacker_headers = build_runtime_headers(
        container_id="runtime-attacker",
        internal_token="attacker-token",
    )
    payload = {
        "id": "cfg-owner",
        "config_id": "cfg-owner",
        "device_id": "sim-thinq-ac",
        "device_type": "DEVICE_AIR_CONDITIONER",
        "country_code": "US",
        "simulation_mode": True,
    }

    with TestClient(app) as client:
        incomplete = client.post(
            "/config",
            json=payload,
            headers={"X-Container-Id": "runtime-owner"},
        )
        configured = client.post("/config", json=payload, headers=legitimate_headers)
        takeover = client.post(
            "/config",
            json={**payload, "id": "cfg-attacker", "config_id": "cfg-attacker"},
            headers=attacker_headers,
        )
        unauthenticated_remove = client.post(
            "/deconfigure",
            json={"config": {"id": "cfg-owner"}},
        )
        wrong_remove = client.post(
            "/deconfigure",
            json={"config": {"id": "cfg-owner"}},
            headers=attacker_headers,
        )
        removed = client.post(
            "/deconfigure",
            json={"config": {"id": "cfg-owner"}},
            headers=legitimate_headers,
        )

    assert incomplete.status_code == 401
    assert configured.status_code == 200
    assert takeover.status_code == 401
    assert unauthenticated_remove.status_code == 401
    assert wrong_remove.status_code == 401
    assert registry.get("cfg-attacker") is None
    assert runtime_context.auth.container_id == "runtime-owner"
    assert runtime_context.auth.internal_token == "owner-token"
    assert removed.status_code == 200
    assert registry.get("cfg-owner") is None


def test_entities_and_state_include_read_only_device(mock_core, monkeypatch) -> None:
    reset_runtime_state()

    async def fake_fetch_device_snapshot(**_kwargs):
        return _fridge_snapshot()

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())

    headers = build_runtime_headers(container_id="runtime-789", internal_token="secret-token")

    with TestClient(app) as client:
        config_response = client.post(
            "/config",
            json={
                "id": "cfg-fridge-1",
                "config_id": "cfg-fridge-1",
                "device_id": "fridge-1",
                "device_name": "Kitchen Fridge",
                "device_type": "DEVICE_REFRIGERATOR",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200
        entities = entities_response.json()["entities"]
        assert len(entities) == 1
        assert entities[0]["device_type"] == "DEVICE_REFRIGERATOR"
        assert entities[0]["capabilities"] == [
            "appliance_state",
            "door",
            "door_open",
            "filter_life",
            "mode",
            "power",
            "refresh",
            "switch",
            "target_temperature",
        ]
        assert [command["id"] for command in entities[0]["available_commands"]] == [
            "refresh",
            "set_target_temperature",
            "enable_express_mode",
            "disable_express_mode",
            "enable_power_save",
            "disable_power_save",
        ]
        temperature_command = next(
            command for command in entities[0]["available_commands"] if command["id"] == "set_target_temperature"
        )
        assert temperature_command["args_schema"]["temperature"]["minimum"] == 1.0
        assert temperature_command["args_schema"]["temperature"]["maximum"] == 7.0
        assert temperature_command["args_schema"]["temperature"]["unit"] == "°C"
        assert entities[0]["metadata"]["documented_commands"] == [
            "refresh",
            "set_target_temperature",
            "enable_power_save",
            "disable_power_save",
            "enable_eco_friendly",
            "disable_eco_friendly",
            "enable_express_mode",
            "disable_express_mode",
            "enable_express_fridge",
            "disable_express_fridge",
            "enable_rapid_freeze",
            "disable_rapid_freeze",
            "enable_sabbath_mode",
            "disable_sabbath_mode",
        ]
        assert entities[0]["metadata"]["device_profile"]["documented_resources"] == [
            "power_save",
            "eco_friendly",
            "sabbath",
            "refrigeration",
            "water_filter_info",
            "door_status",
            "temperature",
        ]
        assert "door_state" in entities[0]["metadata"]["device_profile"]["documented_properties"]

        unauthenticated_state = client.get("/state", params={"device_id": "fridge-1"})
        state_response = client.get(
            "/state",
            params={"device_id": "fridge-1"},
            headers=headers,
        )
        assert unauthenticated_state.status_code == 401
        assert state_response.status_code == 200
        payload = state_response.json()
        assert payload["state_scope"] == "identity-addressed"
        state = payload["entries"]["cfg-fridge-1"]
        assert state["config_id"] == "cfg-fridge-1"
        assert state["latest_state"]["device_name"] == "Kitchen Fridge"
        assert state["latest_state"]["fresh_air_filter_remain_percent"] == 81


def test_multi_config_refresh_isolates_same_device_config_identities(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())
    headers = build_runtime_headers(container_id="runtime-multi", internal_token="secret-token")
    healthy = {
        "id": "cfg-healthy",
        "config_id": "cfg-healthy",
        "device_id": "sim-thinq-ac",
        "device_type": "DEVICE_AIR_CONDITIONER",
        "country_code": "US",
        "simulation_mode": True,
    }
    offline = {
        "id": "cfg-offline",
        "config_id": "cfg-offline",
        "device_id": "sim-thinq-ac",
        "device_type": "DEVICE_AIR_CONDITIONER",
        "country_code": "US",
        "simulation_mode": True,
    }

    with TestClient(app) as client:
        assert client.post("/config", json=healthy, headers=headers).status_code == 200
        assert client.post("/config", json=offline, headers=headers).status_code == 200

        original_refresh = state_module.trigger_refresh

        async def refresh_with_offline_isolation(device_id: str):
            if device_id == "cfg-offline":
                raise HTTPException(status_code=502, detail="offline")
            return await original_refresh(device_id)

        monkeypatch.setattr(state_module, "trigger_refresh", refresh_with_offline_isolation)
        response = client.get("/state?refresh=true", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["entries"]) == {"cfg-healthy"}
    assert payload["entries"]["cfg-healthy"]["device_id"] == "sim-thinq-ac"
    assert payload["failures"] == {
        "cfg-offline": {
            "config_id": "cfg-offline",
            "device_id": "sim-thinq-ac",
            "status_code": 502,
            "available": False,
        }
    }


def test_command_route_rejects_unsupported_command(mock_core, monkeypatch) -> None:
    reset_runtime_state()

    async def fake_fetch_device_snapshot(**_kwargs):
        return _fridge_snapshot()

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())

    headers = build_runtime_headers(container_id="runtime-999", internal_token="secret-token")

    with TestClient(app) as client:
        client.post(
            "/config",
            json={
                "id": "cfg-fridge-1",
                "config_id": "cfg-fridge-1",
                "device_id": "fridge-1",
                "device_name": "Kitchen Fridge",
                "device_type": "DEVICE_REFRIGERATOR",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        response = client.post(
            "/command",
            json={
                "device_id": "fridge-1",
                "command": "turn_on",
                "args": {},
            },
            headers=headers,
        )

    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]


def test_command_route_dispatches_family_specific_refrigerator_control(mock_core, monkeypatch) -> None:
    reset_runtime_state()
    executed: list[dict] = []

    async def fake_fetch_device_snapshot(**_kwargs):
        return _fridge_snapshot()

    async def fake_execute_device_command(**kwargs):
        executed.append(kwargs)
        return {"status": "ok", "control_method": kwargs["control_method"]}

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module.thinq_client, "execute_device_command", fake_execute_device_command)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())

    headers = build_runtime_headers(container_id="runtime-fridge", internal_token="secret-token")

    with TestClient(app) as client:
        config_response = client.post(
            "/config",
            json={
                "id": "cfg-fridge-1",
                "config_id": "cfg-fridge-1",
                "device_id": "fridge-1",
                "device_name": "Kitchen Fridge",
                "device_type": "DEVICE_REFRIGERATOR",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert config_response.status_code == 200

        headers["X-PiPhi-Idempotency-Key"] = "thinq-action-idempotency-1"
        response = client.post(
            "/command",
            json={
                "device_id": "fridge-1",
                "command": "enable_express_mode",
                "args": {},
            },
            headers=headers,
        )
        replay = client.post(
            "/command",
            json={
                "device_id": "fridge-1",
                "command": "enable_express_mode",
                "args": {},
            },
            headers=headers,
        )

    assert response.status_code == 200
    assert replay.status_code == 200
    assert response.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert len(executed) == 1
    assert executed[0]["control_method"] == "set_express_mode"
    assert executed[0]["control_params"] == {"express_mode": "ON"}
    assert response.json()["result"]["status"] == "ok"


def test_command_route_dispatches_safe_profile_mapped_control(mock_core, monkeypatch) -> None:
    reset_runtime_state()
    executed: list[dict] = []

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    async def fake_execute_device_command(**kwargs):
        executed.append(kwargs)
        return {"status": "ok", "control_method": kwargs["control_method"]}

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module.thinq_client, "execute_device_command", fake_execute_device_command)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())

    headers = build_runtime_headers(container_id="runtime-321", internal_token="secret-token")

    with TestClient(app) as client:
        config_response = client.post(
            "/config",
            json={
                "id": "cfg-ac-1",
                "config_id": "cfg-ac-1",
                "device_id": "device-ac-1",
                "device_name": "Living Room AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert config_response.status_code == 200

        missing_auth = client.post(
            "/command",
            json={
                "device_id": "device-ac-1",
                "command": "set_mode",
                "args": {"mode": "HEAT"},
            },
        )
        wrong_auth = client.post(
            "/command",
            json={
                "device_id": "device-ac-1",
                "command": "set_mode",
                "args": {"mode": "HEAT"},
            },
            headers=build_runtime_headers(
                container_id="runtime-321",
                internal_token="wrong-token",
            ),
        )
        assert executed == []
        response = client.post(
            "/command",
            json={
                "device_id": "device-ac-1",
                "command": "set_mode",
                "args": {"mode": "HEAT"},
            },
            headers={**headers, "X-PiPhi-Idempotency-Key": "authenticated-mode"},
        )

    assert missing_auth.status_code == 401
    assert wrong_auth.status_code == 401
    assert response.status_code == 200
    assert executed[0]["control_method"] == "set_mode"
    assert executed[0]["control_params"] == {"mode": "HEAT"}
    assert response.json()["result"]["status"] == "ok"


@pytest.mark.parametrize(
    ("args", "detail"),
    [
        ({}, "Missing required argument"),
        ({"temperature": 15}, "must be at least 16"),
        ({"temperature": 31}, "must be at most 30"),
        ({"temperature": "24"}, "must be a number"),
        ({"temperature": 24, "surprise": True}, "Unknown argument"),
    ],
)
def test_command_route_rejects_invalid_negotiated_args_without_mutation(
    mock_core,
    monkeypatch,
    args,
    detail,
) -> None:
    reset_runtime_state()
    executed: list[dict] = []

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    async def fake_execute_device_command(**kwargs):
        executed.append(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module.thinq_client, "execute_device_command", fake_execute_device_command)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())

    headers = build_runtime_headers(container_id="runtime-safe", internal_token="secret-token")

    with TestClient(app) as client:
        configured = client.post(
            "/config",
            json={
                "id": "cfg-ac-safe",
                "config_id": "cfg-ac-safe",
                "device_id": "device-ac-1",
                "device_name": "Living Room AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert configured.status_code == 200
        before = deepcopy(registry.get("cfg-ac-safe")["latest_state"])
        response = client.post(
            "/command",
            json={
                "device_id": "device-ac-1",
                "command": "set_target_temperature",
                "args": args,
            },
            headers={**headers, "X-PiPhi-Idempotency-Key": f"invalid-{detail}-{args!r}"},
        )
        after = registry.get("cfg-ac-safe")["latest_state"]

    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert executed == []
    assert after == before


@pytest.mark.parametrize(
    "bounds",
    [
        {"minimum": None, "maximum": 30},
        {"minimum": "16", "maximum": 30},
        {"minimum": math.nan, "maximum": 30},
        {"minimum": 16, "maximum": math.inf},
        {"minimum": 30, "maximum": 16},
    ],
)
def test_temperature_command_rejects_invalid_negotiated_bounds_without_mutation(
    mock_core,
    monkeypatch,
    bounds,
) -> None:
    reset_runtime_state()
    executed: list[dict] = []

    async def fake_fetch_device_snapshot(**_kwargs):
        snapshot = _ac_snapshot()
        temperature = snapshot["available_controls"][2]["parameters"][0]
        temperature["min"] = bounds["minimum"]
        temperature["max"] = bounds["maximum"]
        return snapshot

    async def fake_execute_device_command(**kwargs):
        executed.append(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module.thinq_client, "execute_device_command", fake_execute_device_command)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())
    headers = build_runtime_headers(container_id="runtime-bounds", internal_token="secret-token")

    with TestClient(app) as client:
        configured = client.post(
            "/config",
            json={
                "id": "cfg-ac-bounds",
                "device_id": "device-ac-1",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert configured.status_code == 200
        before = deepcopy(registry.get("cfg-ac-bounds")["latest_state"])
        response = client.post(
            "/command",
            json={
                "device_id": "device-ac-1",
                "command": "set_target_temperature",
                "args": {"temperature": 25},
            },
            headers={**headers, "X-PiPhi-Idempotency-Key": f"bounds-{bounds!r}"},
        )
        after = registry.get("cfg-ac-bounds")["latest_state"]

    assert response.status_code == 400
    assert "negotiated safety contract is invalid" in response.json()["detail"]
    assert executed == []
    assert after == before


@pytest.mark.parametrize(
    ("schema", "args"),
    [
        ({}, {}),
        ({"temperature": "not-an-object"}, {}),
        (
            {
                "temperature": {
                    "type": "string",
                    "required": True,
                    "minimum": 16,
                    "maximum": 30,
                }
            },
            {"temperature": "25"},
        ),
    ],
)
def test_temperature_command_rejects_invalid_schema_shapes_without_mutation(
    mock_core,
    monkeypatch,
    schema,
    args,
) -> None:
    reset_runtime_state()
    executed: list[dict] = []

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    async def fake_execute_device_command(**kwargs):
        executed.append(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module.thinq_client, "execute_device_command", fake_execute_device_command)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())
    headers = build_runtime_headers(container_id="runtime-schema", internal_token="secret-token")

    with TestClient(app) as client:
        configured = client.post(
            "/config",
            json={
                "id": "cfg-ac-schema",
                "device_id": "device-ac-1",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert configured.status_code == 200
        state = registry.get("cfg-ac-schema")["latest_state"]
        command = next(
            item
            for item in state["available_commands"]
            if item["id"] == "set_target_temperature"
        )
        command["args_schema"] = schema
        before = deepcopy(state)
        response = client.post(
            "/command",
            json={
                "device_id": "device-ac-1",
                "command": "set_target_temperature",
                "args": args,
            },
            headers={**headers, "X-PiPhi-Idempotency-Key": f"schema-{schema!r}"},
        )
        after = registry.get("cfg-ac-schema")["latest_state"]

    assert response.status_code == 400
    assert "negotiated safety contract is invalid" in response.json()["detail"]
    assert executed == []
    assert after == before


@pytest.mark.parametrize(
    ("schema", "value", "detail"),
    [
        ({"type": "string", "required": True, "options": ["COOL", "HEAT"]}, "DRY", "must be one of"),
        ({"type": "integer", "required": True}, 1.5, "must be an integer"),
        ({"type": "boolean", "required": True}, "true", "must be a boolean"),
        ({"type": "string", "required": True}, 42, "must be a string"),
        ({"type": "string", "required": True, "options": [1]}, 1, "must be a string"),
        ({"type": "number", "required": True}, 10**1000, "must be finite"),
    ],
)
def test_command_route_rejects_each_negotiated_type_without_mutation(
    mock_core,
    monkeypatch,
    schema,
    value,
    detail,
) -> None:
    reset_runtime_state()
    executed: list[dict] = []

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    async def fake_execute_device_command(**kwargs):
        executed.append(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module.thinq_client, "execute_device_command", fake_execute_device_command)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())
    headers = build_runtime_headers(container_id="runtime-types", internal_token="secret-token")

    with TestClient(app) as client:
        configured = client.post(
            "/config",
            json={
                "id": "cfg-ac-types",
                "device_id": "device-ac-1",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert configured.status_code == 200
        state = registry.get("cfg-ac-types")["latest_state"]
        command = next(item for item in state["available_commands"] if item["id"] == "set_mode")
        command["args_schema"] = {"mode": schema}
        before = deepcopy(state)
        response = client.post(
            "/command",
            json={"device_id": "device-ac-1", "command": "set_mode", "args": {"mode": value}},
            headers={**headers, "X-PiPhi-Idempotency-Key": f"types-{detail}"},
        )
        after = registry.get("cfg-ac-types")["latest_state"]

    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert executed == []
    assert after == before


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_command_route_rejects_non_finite_json_numbers_without_mutation(
    mock_core,
    monkeypatch,
    token,
) -> None:
    reset_runtime_state()
    executed: list[dict] = []

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    async def fake_execute_device_command(**kwargs):
        executed.append(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module.thinq_client, "execute_device_command", fake_execute_device_command)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())
    headers = build_runtime_headers(container_id="runtime-finite", internal_token="secret-token")

    with TestClient(app) as client:
        configured = client.post(
            "/config",
            json={
                "id": "cfg-ac-finite",
                "device_id": "device-ac-1",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert configured.status_code == 200
        state = registry.get("cfg-ac-finite")["latest_state"]
        command = next(item for item in state["available_commands"] if item["id"] == "set_mode")
        command["args_schema"] = {"mode": {"type": "number", "required": True}}
        before = deepcopy(state)
        response = client.post(
            "/command",
            content=(
                '{"device_id":"device-ac-1","command":"set_mode",'
                f'"args":{{"mode":{token}}}}}'
            ),
            headers={
                **headers,
                "Content-Type": "application/json",
                "X-PiPhi-Idempotency-Key": f"finite-{token}",
            },
        )
        after = registry.get("cfg-ac-finite")["latest_state"]

    assert response.status_code == 400
    assert "must be finite" in response.json()["detail"]
    assert executed == []
    assert after == before


def test_command_route_accepts_in_range_temperature_and_reads_it_back() -> None:
    reset_runtime_state()
    config_module.simulator_client.__init__()
    headers = build_runtime_headers(container_id="runtime-sim", internal_token="secret-token")

    with TestClient(app) as client:
        configured = client.post(
            "/config",
            json={
                "id": "cfg-sim-ac",
                "config_id": "cfg-sim-ac",
                "device_id": "sim-thinq-ac",
                "device_name": "Simulated Living Room AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "country_code": "US",
                "simulation_mode": True,
            },
            headers=headers,
        )
        assert configured.status_code == 200
        response = client.post(
            "/command",
            json={
                "device_id": "sim-thinq-ac",
                "command": "set_target_temperature",
                "args": {"temperature": 25},
            },
            headers={**headers, "X-PiPhi-Idempotency-Key": "valid-temperature-25"},
        )
        readback = client.get(
            "/state",
            params={"device_id": "sim-thinq-ac", "refresh": "true"},
            headers=headers,
        )

    assert response.status_code == 200
    assert readback.status_code == 200
    assert (
        readback.json()["entries"]["cfg-sim-ac"]["latest_state"]["target_temperature_c"]
        == 25
    )


def test_entities_expose_documented_profile_for_device_type(mock_core, monkeypatch) -> None:
    reset_runtime_state()

    async def fake_fetch_device_snapshot(**_kwargs):
        return _ac_snapshot()

    monkeypatch.setattr(config_module.telemetry_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.event_client, "core_base_url", mock_core.base_url)
    monkeypatch.setattr(config_module.thinq_client, "fetch_device_snapshot", fake_fetch_device_snapshot)
    monkeypatch.setattr(config_module, "start_device_poll_task", lambda **_kwargs: _DummyTask())

    headers = build_runtime_headers(container_id="runtime-222", internal_token="secret-token")

    with TestClient(app) as client:
        config_response = client.post(
            "/config",
            json={
                "id": "cfg-ac-1",
                "config_id": "cfg-ac-1",
                "device_id": "device-ac-1",
                "device_name": "Living Room AC",
                "device_type": "DEVICE_AIR_CONDITIONER",
                "access_token": "pat-1",
                "country_code": "US",
            },
            headers=headers,
        )
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200
        entity = entities_response.json()["entities"][0]

    assert entity["entity_type"] == "thermostat"
    assert entity["capabilities"] == [
        "brightness",
        "fan_speed",
        "filter_life",
        "humidity",
        "mode",
        "pm1",
        "pm10",
        "pm2",
        "refresh",
        "switch",
        "target_temperature",
        "temperature",
    ]
    assert entity["metadata"]["documented_commands"] == [
        "refresh",
        "turn_on",
        "turn_off",
        "toggle",
        "set_mode",
        "set_target_temperature",
        "set_fan_speed",
        "set_brightness",
    ]
    assert entity["metadata"]["device_profile"]["documented_resources"] == [
        "operation",
        "temperature",
        "air_flow",
        "air_quality_sensor",
        "filter_info",
        "display",
        "wind_direction",
    ]
    assert "current_temperature_c" in entity["metadata"]["device_profile"]["documented_properties"]
    assert entity["available_commands"][0]["id"] == "refresh"


def test_command_catalog_infers_numeric_enum_type() -> None:
    commands, _mapping = build_command_catalog(
        device_type="DEVICE_AIR_CONDITIONER",
        capabilities=["fan_speed"],
        available_controls=[
            {
                "method": "set_fan_speed",
                "parameters": [{"name": "fan_speed", "options": [1, 2, 3, 4]}],
            }
        ],
    )

    fan_speed = next(command for command in commands if command["id"] == "set_fan_speed")
    assert fan_speed["args_schema"]["speed"]["type"] == "integer"
    assert fan_speed["args_schema"]["speed"]["options"] == [1, 2, 3, 4]
