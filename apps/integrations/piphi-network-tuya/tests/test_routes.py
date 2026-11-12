from __future__ import annotations

import asyncio
import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from piphi_runtime_testkit_python import (
    assert_entities_response,
    assert_event_sent,
    assert_telemetry_sent,
    build_config_payload,
    build_config_snapshot,
    build_runtime_headers,
)

from piphi_network_tuya.main import app
from piphi_network_tuya.settings import INTEGRATION_VERSION
from piphi_network_tuya.state import (
    close_device_session,
    device_sessions,
    event_client,
    poll_tasks,
    registry,
    runtime,
    telemetry,
)

state_module = importlib.import_module("piphi_network_tuya.state")
discovery_module = importlib.import_module("piphi_network_tuya.tuya")


def reset_runtime_state() -> None:
    for task in list(poll_tasks.values()):
        try:
            task.cancel()
        except Exception:
            pass
    poll_tasks.clear()
    for config_id in list(device_sessions.keys()):
        close_device_session(config_id)
    device_sessions.clear()
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime.auth.container_id = ""
    runtime.auth.internal_token = ""
    runtime.process_state.background_tasks.clear()


def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for background delivery to complete.")


async def fake_read_plug_status(config, *, device=None) -> SimpleNamespace:
    return SimpleNamespace(
        metrics={
            "connected": True,
            "power": True,
            "latency_ms": 12.5,
            "dp_count": 4,
            "protocol_version": config.version,
            "current_ma": 120,
            "power_w": 8.2,
            "voltage_v": 119.4,
            "dp_1": True,
            "dp_18": 120,
            "dp_19": 82,
            "dp_20": 1194,
        },
        units={
            "connected": "bool",
            "power": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
            "current_ma": "mA",
            "power_w": "W",
            "voltage_v": "V",
            "dp_1": "bool",
            "dp_18": "count",
            "dp_19": "count",
            "dp_20": "count",
        },
        raw={"dps": {"1": True, "18": 120, "19": 82, "20": 1194}},
    )


async def fake_read_light_status(config, *, device=None) -> SimpleNamespace:
    return SimpleNamespace(
        metrics={
            "connected": True,
            "power": True,
            "latency_ms": 10.2,
            "dp_count": 5,
            "protocol_version": config.version,
            "mode": "white",
            "brightness_percent": 65.0,
            "color_temp_percent": 40.0,
            "color_value": "00ff00ffff00",
            "dp_20": True,
            "dp_21": "white",
            "dp_22": 650,
            "dp_23": 400,
            "dp_24": "00ff00ffff00",
        },
        units={
            "connected": "bool",
            "power": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
            "mode": "string",
            "brightness_percent": "%",
            "color_temp_percent": "%",
            "color_value": "string",
            "dp_20": "bool",
            "dp_21": "string",
            "dp_22": "count",
            "dp_23": "count",
            "dp_24": "string",
        },
        raw={
            "dps": {
                "20": True,
                "21": "white",
                "22": 650,
                "23": 400,
                "24": "00ff00ffff00",
            }
        },
    )


async def fake_read_fan_status(config, *, device=None) -> SimpleNamespace:
    return SimpleNamespace(
        metrics={
            "connected": True,
            "power": True,
            "latency_ms": 9.8,
            "dp_count": 4,
            "protocol_version": config.version,
            "fan_speed_percent": 67.0,
            "oscillating": True,
            "mode": "normal",
            "dp_1": True,
            "dp_3": 2,
            "dp_4": "normal",
            "dp_5": True,
        },
        units={
            "connected": "bool",
            "power": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
            "fan_speed_percent": "%",
            "oscillating": "bool",
            "mode": "string",
            "dp_1": "bool",
            "dp_3": "count",
            "dp_4": "string",
            "dp_5": "bool",
        },
        raw={"dps": {"1": True, "3": 2, "4": "normal", "5": True}},
    )


async def fake_read_cover_status(config, *, device=None) -> SimpleNamespace:
    return SimpleNamespace(
        metrics={
            "connected": True,
            "latency_ms": 14.0,
            "dp_count": 2,
            "protocol_version": config.version,
            "motion_state": "stopped",
            "position_percent": 50.0,
            "dp_1": "stop",
            "dp_2": 50,
        },
        units={
            "connected": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
            "motion_state": "string",
            "position_percent": "%",
            "dp_1": "string",
            "dp_2": "count",
        },
        raw={"dps": {"1": "stop", "2": 50}},
    )


async def fake_read_climate_status(config, *, device=None) -> SimpleNamespace:
    return SimpleNamespace(
        metrics={
            "connected": True,
            "power": True,
            "latency_ms": 11.3,
            "dp_count": 4,
            "protocol_version": config.version,
            "mode": "auto",
            "temperature_c": 19.5,
            "target_temperature_c": 21.0,
            "dp_1": True,
            "dp_16": 210,
            "dp_24": 195,
            "dp_4": "auto",
        },
        units={
            "connected": "bool",
            "power": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
            "mode": "string",
            "temperature_c": "C",
            "target_temperature_c": "C",
            "dp_1": "bool",
            "dp_16": "count",
            "dp_24": "count",
            "dp_4": "string",
        },
        raw={"dps": {"1": True, "16": 210, "24": 195, "4": "auto"}},
    )


async def fake_read_humidifier_status(config, *, device=None) -> SimpleNamespace:
    return SimpleNamespace(
        metrics={
            "connected": True,
            "power": True,
            "latency_ms": 8.7,
            "dp_count": 4,
            "protocol_version": config.version,
            "mode": "auto",
            "humidity_percent": 48.0,
            "target_humidity_percent": 55.0,
            "dp_1": True,
            "dp_2": "auto",
            "dp_103": 55,
            "dp_104": 48,
        },
        units={
            "connected": "bool",
            "power": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
            "mode": "string",
            "humidity_percent": "%",
            "target_humidity_percent": "%",
            "dp_1": "bool",
            "dp_2": "string",
            "dp_103": "count",
            "dp_104": "count",
        },
        raw={"dps": {"1": True, "2": "auto", "103": 55, "104": 48}},
    )


async def fake_read_air_purifier_status(config, *, device=None) -> SimpleNamespace:
    return SimpleNamespace(
        metrics={
            "connected": True,
            "power": True,
            "latency_ms": 7.9,
            "dp_count": 4,
            "protocol_version": config.version,
            "mode": "auto",
            "fan_speed_percent": 100.0,
            "air_quality_index": 35,
            "dp_1": True,
            "dp_2": "auto",
            "dp_4": 3,
            "dp_22": 35,
        },
        units={
            "connected": "bool",
            "power": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
            "mode": "string",
            "fan_speed_percent": "%",
            "air_quality_index": "AQI",
            "dp_1": "bool",
            "dp_2": "string",
            "dp_4": "count",
            "dp_22": "count",
        },
        raw={"dps": {"1": True, "2": "auto", "4": 3, "22": 35}},
    )


async def fake_read_failure(config, *, device=None) -> SimpleNamespace:
    raise discovery_module.TuyaClientError("device authentication failed")


def test_ui_config_exposes_tuya_credentials_and_cloud_discovery_fields() -> None:
    with TestClient(app) as client:
        response = client.get("/ui-config")

    body = response.json()
    assert response.status_code == 200
    assert {"host", "tuya_device_id", "local_key"}.issubset(body["schema"]["required"])
    assert "api_region" in body["schema"]["properties"]
    assert body["schema"]["properties"]["device_type"]["description"].startswith(
        "Can be prefilled from discovery"
    )
    assert {"fan", "cover", "climate", "humidifier", "air_purifier"}.issubset(
        set(body["schema"]["properties"]["device_type"]["enum"])
    )
    assert body["uiSchema"]["local_key"]["ui:widget"] == "password"
    assert body["uiSchema"]["api_secret"]["ui:widget"] == "password"
    assert body["uiSchema"]["switch"]["ui:help"].startswith(
        "For switches, plugs, and many fans"
    )
    assert body["discovery_defaults"]["source"] == "discover.devices[].suggested_config"
    assert body["discovery_defaults"]["apply_fields"] == [
        "device_type",
        "switch",
        "version",
        "fan_speed_dp",
        "fan_speed_max",
        "fan_oscillate_dp",
        "fan_mode_dp",
        "cover_control_dp",
        "cover_position_dp",
        "climate_target_temp_dp",
        "climate_current_temp_dp",
        "climate_mode_dp",
        "climate_temp_scale",
        "humidifier_target_humidity_dp",
        "humidifier_current_humidity_dp",
        "humidifier_mode_dp",
        "humidifier_humidity_scale",
        "purifier_speed_dp",
        "purifier_speed_max",
        "purifier_mode_dp",
        "purifier_aqi_dp",
        "purifier_aqi_scale",
    ]
    assert body["discovery_defaults"]["field_mapping"]["switch"]["from"] == (
        "suggested_config.switch"
    )
    assert (
        body["discovery_defaults"]["field_mapping"]["climate_target_temp_dp"]["from"]
        == "suggested_config.climate_target_temp_dp"
    )
    assert (
        body["discovery_defaults"]["field_mapping"]["climate_temp_scale"]["from"]
        == "suggested_config.climate_temp_scale"
    )
    assert (
        body["discovery_defaults"]["field_mapping"]["humidifier_target_humidity_dp"][
            "from"
        ]
        == "suggested_config.humidifier_target_humidity_dp"
    )
    assert (
        body["discovery_defaults"]["field_mapping"]["humidifier_humidity_scale"]["from"]
        == "suggested_config.humidifier_humidity_scale"
    )
    assert (
        body["discovery_defaults"]["field_mapping"]["purifier_speed_dp"]["from"]
        == "suggested_config.purifier_speed_dp"
    )
    assert (
        body["discovery_defaults"]["field_mapping"]["purifier_aqi_scale"]["from"]
        == "suggested_config.purifier_aqi_scale"
    )
    assert "resolved_config_preview" in body["discovery_defaults"]["display_fields"]


def test_manifest_route_reports_tinytuya_and_manifest_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/manifest.json")

    body = response.json()
    assert response.status_code == 200
    assert body["id"] == "piphi-network-tuya"
    assert body["version"] == INTEGRATION_VERSION
    assert body["image"] == (
        f"docker.io/piphinetwork/piphi-network-tuya:{INTEGRATION_VERSION}"
    )
    assert body["runtime"]["linux"]["container"]["image"] == body["image"]
    assert body["metadata"]["vendor_library"] == "tinytuya"
    assert body["api"]["endpoints"]["manifest"] == "/manifest.json"
    assert body["api"]["endpoints"]["behaviors"] == "/behaviors.json"
    assert body["api"]["endpoints"]["manifest_static"] == "/manifest.static.json"
    assert body["api"]["endpoints"]["behaviors_static"] == "/behaviors.static.json"
    assert body["runtime"]["linux"]["discovery"]["inputs"][0]["name"] == "lan_scan"


def test_manifest_static_route_matches_checked_in_file() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / "src" / "manifest.json"
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))

    with TestClient(app) as client:
        response = client.get("/manifest.static.json")

    assert response.status_code == 200
    assert response.json() == expected


def test_behaviors_route_reports_plug_light_fan_cover_climate_humidifier_and_air_purifier_profiles() -> (
    None
):
    with TestClient(app) as client:
        response = client.get("/behaviors.json")

    body = response.json()
    assert response.status_code == 200
    ids = {device["id"] for device in body["devices"]}
    assert {
        "tuya_plug",
        "tuya_light",
        "tuya_fan",
        "tuya_cover",
        "tuya_climate",
        "tuya_humidifier",
        "tuya_air_purifier",
    }.issubset(ids)

    by_id = {device["id"]: device for device in body["devices"]}
    light_action_ids = {action["id"] for action in by_id["tuya_light"]["actions"]}
    fan_action_ids = {action["id"] for action in by_id["tuya_fan"]["actions"]}
    cover_action_ids = {action["id"] for action in by_id["tuya_cover"]["actions"]}
    purifier_condition_ids = {
        condition["id"] for condition in by_id["tuya_air_purifier"]["conditions"]
    }
    climate_condition_ids = {
        condition["id"] for condition in by_id["tuya_climate"]["conditions"]
    }
    standardized_condition_order = {
        device_id: [condition["id"] for condition in by_id[device_id]["conditions"][:2]]
        for device_id in [
            "tuya_plug",
            "tuya_light",
            "tuya_fan",
            "tuya_climate",
            "tuya_humidifier",
            "tuya_air_purifier",
        ]
    }

    assert {"set_mode", "refresh"}.issubset(light_action_ids)
    assert {"set_mode", "refresh"}.issubset(fan_action_ids)
    assert "refresh" in cover_action_ids
    assert {"fan_speed", "power_state", "connected"}.issubset(purifier_condition_ids)
    assert {"target_temperature", "power_state", "connected"}.issubset(
        climate_condition_ids
    )
    for condition_ids in standardized_condition_order.values():
        assert condition_ids == ["connected", "power_state"]
    assert by_id["tuya_cover"]["conditions"][0]["id"] == "connected"


def test_behaviors_static_route_matches_checked_in_file() -> None:
    behaviors_path = Path(__file__).resolve().parents[1] / "src" / "behaviors.json"
    expected = json.loads(behaviors_path.read_text(encoding="utf-8"))

    with TestClient(app) as client:
        response = client.get("/behaviors.static.json")

    assert response.status_code == 200
    assert response.json() == expected


def test_discover_returns_manual_candidate_without_cloud_credentials() -> None:
    reset_runtime_state()
    with TestClient(app) as client:
        response = client.post(
            "/discover",
            json={
                "inputs": {
                    "host": "10.0.0.50",
                    "tuya_device_id": "bf123",
                    "alias": "Desk Plug",
                }
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["devices"][0]["tuya_device_id"] == "bf123"
    assert body["devices"][0]["host"] == "10.0.0.50"
    assert body["devices"][0]["alias"] == "Desk Plug"
    assert body["devices"][0]["device_type"] == "plug"
    assert body["devices"][0]["entity_type"] == "switch"
    assert body["devices"][0]["device_class"] == "outlet"
    assert body["devices"][0]["suggested_config"]["device_type"] == "plug"
    assert body["devices"][0]["resolved_config_preview"]["host"] == "10.0.0.50"
    assert body["devices"][0]["resolved_config_preview"]["version"] == "3.3"
    assert body["devices"][0]["missing_required_fields"] == ["local_key"]


def test_discover_can_return_tinytuya_lan_scan_results(monkeypatch) -> None:
    reset_runtime_state()

    class _FakeTinyTuya:
        @staticmethod
        def deviceScan(**kwargs):
            return {
                "10.0.0.70": {
                    "gwId": "bfscan123",
                    "version": "3.3",
                    "productName": "Hall Plug",
                    "dps": {"1": True},
                },
                "10.0.0.71": {
                    "gwId": "bfscan999",
                    "version": "3.3",
                    "productName": "Other Plug",
                    "dps": {"1": False},
                },
                "10.0.0.72": {
                    "gwId": "bflight123",
                    "version": "3.3",
                    "productName": "Mystery Device",
                    "dps": {
                        "20": True,
                        "21": "white",
                        "22": 650,
                        "23": 400,
                        "24": "00ff00ffff00",
                    },
                },
                "10.0.0.73": {
                    "gwId": "bfswitch321",
                    "version": "3.3",
                    "category": "kg",
                    "productName": "Entry Switch",
                    "dps": {"1": True, "2": False, "3": True},
                },
                "10.0.0.74": {
                    "gwId": "bffan123",
                    "version": "3.3",
                    "productName": "Bedroom Fan",
                    "dps": {"1": True, "3": 2, "4": "normal", "5": True},
                },
                "10.0.0.75": {
                    "gwId": "bfcover123",
                    "version": "3.3",
                    "productName": "Window Blind",
                    "dps": {"1": "stop", "2": 50},
                },
                "10.0.0.76": {
                    "gwId": "bfclimate123",
                    "version": "3.3",
                    "category": "wk",
                    "productName": "Hall Thermostat",
                    "dps": {"1": True, "16": 210, "24": 195, "4": "auto"},
                },
                "10.0.0.77": {
                    "gwId": "bfhumid123",
                    "version": "3.3",
                    "category": "jsq",
                    "productName": "Bedroom Humidifier",
                    "dps": {"1": True, "2": "auto", "103": 55, "104": 48},
                },
                "10.0.0.78": {
                    "gwId": "bfpurifier123",
                    "version": "3.3",
                    "category": "kj",
                    "productName": "Bedroom Air Purifier",
                    "dps": {"1": True, "2": "auto", "4": 3, "22": 35},
                },
            }

    monkeypatch.setattr(discovery_module, "tinytuya", _FakeTinyTuya)

    devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "host": "10.0.0.70",
                "tuya_device_id": "bfscan123",
            }
        )
    )

    assert len(devices) == 1
    assert devices[0]["tuya_device_id"] == "bfscan123"
    assert devices[0]["host"] == "10.0.0.70"
    assert devices[0]["device_type"] == "plug"
    assert devices[0]["device_class"] == "outlet"
    assert devices[0]["entity_type"] == "switch"
    assert devices[0]["discovery_source"] == "lan_scan"
    assert devices[0]["discovery_hints"]["classification_source"] == "product_name"
    assert "power_w" not in devices[0]["supported_capabilities"]
    assert devices[0]["resolved_config_preview"]["tuya_device_id"] == "bfscan123"
    assert devices[0]["resolved_config_preview"]["switch"] == 1
    assert devices[0]["missing_required_fields"] == ["local_key"]

    light_devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "tuya_device_id": "bflight123",
            }
        )
    )

    assert light_devices[0]["device_type"] == "light"
    assert light_devices[0]["entity_type"] == "light"
    assert light_devices[0]["discovery_hints"]["supports_brightness"] is True
    assert light_devices[0]["discovery_hints"]["supports_rgb"] is True
    assert {"set_brightness", "set_color_temp", "set_color_rgb", "set_mode"}.issubset(
        set(light_devices[0]["supported_commands"])
    )

    switch_devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "tuya_device_id": "bfswitch321",
            }
        )
    )

    assert switch_devices[0]["device_type"] == "switch"
    assert switch_devices[0]["device_class"] == "switch"
    assert switch_devices[0]["entity_type"] == "switch"
    assert switch_devices[0]["tuya_category"] == "kg"
    assert (
        switch_devices[0]["discovery_hints"]["classification_source"] == "tuya_category"
    )
    assert switch_devices[0]["discovery_hints"]["supports_multi_switch"] is True
    assert switch_devices[0]["discovery_hints"]["switch_channel_count"] == 3
    assert switch_devices[0]["discovery_hints"]["primary_power_dp"] == "1"
    assert switch_devices[0]["suggested_config"]["switch"] == 1
    assert switch_devices[0]["resolved_config_preview"]["device_type"] == "switch"

    fan_devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "tuya_device_id": "bffan123",
            }
        )
    )

    assert fan_devices[0]["device_type"] == "fan"
    assert fan_devices[0]["device_class"] == "fan"
    assert fan_devices[0]["entity_type"] == "fan"
    assert fan_devices[0]["suggested_config"]["fan_speed_dp"] == 3
    assert fan_devices[0]["suggested_config"]["fan_speed_max"] == 3
    assert fan_devices[0]["supported_commands"] == [
        "refresh",
        "turn_on",
        "turn_off",
        "set_fan_speed",
        "set_oscillate",
        "set_mode",
        "set_dp",
    ]

    cover_devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "tuya_device_id": "bfcover123",
            }
        )
    )

    assert cover_devices[0]["device_type"] == "cover"
    assert cover_devices[0]["device_class"] == "cover"
    assert cover_devices[0]["entity_type"] == "cover"
    assert cover_devices[0]["suggested_config"]["cover_control_dp"] == 1
    assert cover_devices[0]["suggested_config"]["cover_position_dp"] == 2
    assert {"open_cover", "close_cover", "stop_cover", "set_cover_position"}.issubset(
        set(cover_devices[0]["supported_commands"])
    )

    climate_devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "tuya_device_id": "bfclimate123",
            }
        )
    )

    assert climate_devices[0]["device_type"] == "climate"
    assert climate_devices[0]["device_class"] == "climate"
    assert climate_devices[0]["entity_type"] == "climate"
    assert climate_devices[0]["tuya_category"] == "wk"
    assert (
        climate_devices[0]["discovery_hints"]["classification_source"]
        == "tuya_category"
    )
    assert climate_devices[0]["discovery_hints"]["climate_target_temp_dp"] == "16"
    assert climate_devices[0]["discovery_hints"]["climate_current_temp_dp"] == "24"
    assert climate_devices[0]["discovery_hints"]["climate_mode_dp"] == "4"
    assert climate_devices[0]["discovery_hints"]["climate_temp_scale"] == 10.0
    assert climate_devices[0]["suggested_config"]["climate_target_temp_dp"] == 16
    assert climate_devices[0]["suggested_config"]["climate_current_temp_dp"] == 24
    assert climate_devices[0]["suggested_config"]["climate_mode_dp"] == 4
    assert climate_devices[0]["suggested_config"]["climate_temp_scale"] == 10.0
    assert climate_devices[0]["resolved_config_preview"]["climate_target_temp_dp"] == 16
    assert (
        climate_devices[0]["resolved_config_preview"]["climate_current_temp_dp"] == 24
    )
    assert climate_devices[0]["resolved_config_preview"]["climate_mode_dp"] == 4
    assert climate_devices[0]["resolved_config_preview"]["climate_temp_scale"] == 10.0
    assert {"set_temperature", "set_mode"}.issubset(
        set(climate_devices[0]["supported_commands"])
    )

    humidifier_devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "tuya_device_id": "bfhumid123",
            }
        )
    )

    assert humidifier_devices[0]["device_type"] == "humidifier"
    assert humidifier_devices[0]["device_class"] == "humidifier"
    assert humidifier_devices[0]["entity_type"] == "humidifier"
    assert humidifier_devices[0]["tuya_category"] == "jsq"
    assert (
        humidifier_devices[0]["discovery_hints"]["classification_source"]
        == "tuya_category"
    )
    assert (
        humidifier_devices[0]["discovery_hints"]["humidifier_target_humidity_dp"]
        == "103"
    )
    assert (
        humidifier_devices[0]["discovery_hints"]["humidifier_current_humidity_dp"]
        == "104"
    )
    assert humidifier_devices[0]["discovery_hints"]["humidifier_mode_dp"] == "2"
    assert humidifier_devices[0]["discovery_hints"]["humidifier_humidity_scale"] == 1.0
    assert (
        humidifier_devices[0]["suggested_config"]["humidifier_target_humidity_dp"]
        == 103
    )
    assert (
        humidifier_devices[0]["suggested_config"]["humidifier_current_humidity_dp"]
        == 104
    )
    assert humidifier_devices[0]["suggested_config"]["humidifier_mode_dp"] == 2
    assert humidifier_devices[0]["suggested_config"]["humidifier_humidity_scale"] == 1.0
    assert (
        humidifier_devices[0]["resolved_config_preview"][
            "humidifier_target_humidity_dp"
        ]
        == 103
    )
    assert (
        humidifier_devices[0]["resolved_config_preview"][
            "humidifier_current_humidity_dp"
        ]
        == 104
    )
    assert humidifier_devices[0]["resolved_config_preview"]["humidifier_mode_dp"] == 2
    assert (
        humidifier_devices[0]["resolved_config_preview"]["humidifier_humidity_scale"]
        == 1.0
    )
    assert {"set_humidity", "set_mode"}.issubset(
        set(humidifier_devices[0]["supported_commands"])
    )

    purifier_devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "lan_scan": True,
                "scan_seconds": 1,
                "tuya_device_id": "bfpurifier123",
            }
        )
    )

    assert purifier_devices[0]["device_type"] == "air_purifier"
    assert purifier_devices[0]["device_class"] == "air_purifier"
    assert purifier_devices[0]["entity_type"] == "air_purifier"
    assert purifier_devices[0]["tuya_category"] == "kj"
    assert (
        purifier_devices[0]["discovery_hints"]["classification_source"]
        == "tuya_category"
    )
    assert purifier_devices[0]["discovery_hints"]["purifier_speed_dp"] == "4"
    assert purifier_devices[0]["discovery_hints"]["purifier_speed_max"] == 3
    assert purifier_devices[0]["discovery_hints"]["purifier_mode_dp"] == "2"
    assert purifier_devices[0]["discovery_hints"]["purifier_aqi_dp"] == "22"
    assert purifier_devices[0]["discovery_hints"]["purifier_aqi_scale"] == 1.0
    assert purifier_devices[0]["suggested_config"]["purifier_speed_dp"] == 4
    assert purifier_devices[0]["suggested_config"]["purifier_speed_max"] == 3
    assert purifier_devices[0]["suggested_config"]["purifier_mode_dp"] == 2
    assert purifier_devices[0]["suggested_config"]["purifier_aqi_dp"] == 22
    assert purifier_devices[0]["suggested_config"]["purifier_aqi_scale"] == 1.0
    assert purifier_devices[0]["resolved_config_preview"]["purifier_speed_dp"] == 4
    assert purifier_devices[0]["resolved_config_preview"]["purifier_speed_max"] == 3
    assert purifier_devices[0]["resolved_config_preview"]["purifier_mode_dp"] == 2
    assert purifier_devices[0]["resolved_config_preview"]["purifier_aqi_dp"] == 22
    assert purifier_devices[0]["resolved_config_preview"]["purifier_aqi_scale"] == 1.0
    assert {"set_fan_speed", "set_mode"}.issubset(
        set(purifier_devices[0]["supported_commands"])
    )


def test_discover_can_return_tinytuya_cloud_results_with_category_mapping(
    monkeypatch,
) -> None:
    reset_runtime_state()

    class _FakeCloud:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def getdevices(self):
            return {
                "result": [
                    {
                        "id": "cloud-switch-1",
                        "name": "Porch Switch",
                        "category": "kg",
                        "ip": "10.0.0.80",
                        "product_name": "Wall Switch",
                        "product_id": "prod-switch",
                        "version": "3.4",
                    },
                    {
                        "id": "cloud-light-1",
                        "name": "Strip Light",
                        "category": "dj",
                        "local_ip": "10.0.0.81",
                        "product_name": "RGB Strip Light",
                        "product_id": "prod-light",
                        "version": "3.3",
                    },
                    {
                        "id": "cloud-fan-1",
                        "name": "Living Room Fan",
                        "category": "fs",
                        "local_ip": "10.0.0.82",
                        "product_name": "Ceiling Fan",
                        "product_id": "prod-fan",
                        "version": "3.3",
                    },
                    {
                        "id": "cloud-climate-1",
                        "name": "Hall Thermostat",
                        "category": "wk",
                        "local_ip": "10.0.0.83",
                        "product_name": "Radiator Thermostat",
                        "product_id": "prod-climate",
                        "version": "3.3",
                    },
                    {
                        "id": "cloud-humidifier-1",
                        "name": "Bedroom Humidifier",
                        "category": "jsq",
                        "local_ip": "10.0.0.84",
                        "product_name": "Aroma Diffuser",
                        "product_id": "prod-hum",
                        "version": "3.3",
                    },
                    {
                        "id": "cloud-purifier-1",
                        "name": "Bedroom Purifier",
                        "category": "kj",
                        "local_ip": "10.0.0.85",
                        "product_name": "HEPA Air Purifier",
                        "product_id": "prod-purifier",
                        "version": "3.3",
                    },
                ]
            }

    class _FakeTinyTuya:
        Cloud = _FakeCloud

    monkeypatch.setattr(discovery_module, "tinytuya", _FakeTinyTuya)

    devices = asyncio.run(
        discovery_module.discover_devices(
            {
                "api_region": "us",
                "api_key": "key",
                "api_secret": "secret",
            }
        )
    )

    assert len(devices) == 6
    by_id = {device["tuya_device_id"]: device for device in devices}

    switch_device = by_id["cloud-switch-1"]
    assert switch_device["device_type"] == "switch"
    assert switch_device["device_class"] == "switch"
    assert switch_device["entity_type"] == "switch"
    assert switch_device["tuya_category"] == "kg"
    assert switch_device["discovery_hints"]["classification_source"] == "tuya_category"
    assert switch_device["supported_commands"] == [
        "refresh",
        "turn_on",
        "turn_off",
        "set_dp",
    ]

    light_device = by_id["cloud-light-1"]
    assert light_device["device_type"] == "light"
    assert light_device["device_class"] == "light"
    assert light_device["entity_type"] == "light"
    assert light_device["tuya_category"] == "dj"
    assert light_device["discovery_hints"]["classification_source"] == "tuya_category"
    assert light_device["resolved_config_preview"]["version"] == "3.3"
    assert {"set_brightness", "set_color_temp", "set_color_rgb", "set_mode"}.issubset(
        set(light_device["supported_commands"])
    )
    assert {"brightness_percent", "color_temp_percent", "color_value"}.issubset(
        set(light_device["supported_capabilities"])
    )

    fan_device = by_id["cloud-fan-1"]
    assert fan_device["device_type"] == "fan"
    assert fan_device["device_class"] == "fan"
    assert fan_device["entity_type"] == "fan"
    assert fan_device["tuya_category"] == "fs"

    climate_device = by_id["cloud-climate-1"]
    assert climate_device["device_type"] == "climate"
    assert climate_device["device_class"] == "climate"
    assert climate_device["entity_type"] == "climate"
    assert climate_device["tuya_category"] == "wk"
    assert climate_device["discovery_hints"]["classification_source"] == "tuya_category"

    humidifier_device = by_id["cloud-humidifier-1"]
    assert humidifier_device["device_type"] == "humidifier"
    assert humidifier_device["device_class"] == "humidifier"
    assert humidifier_device["entity_type"] == "humidifier"
    assert humidifier_device["tuya_category"] == "jsq"
    assert (
        humidifier_device["discovery_hints"]["classification_source"] == "tuya_category"
    )

    purifier_device = by_id["cloud-purifier-1"]
    assert purifier_device["device_type"] == "air_purifier"
    assert purifier_device["device_class"] == "air_purifier"
    assert purifier_device["entity_type"] == "air_purifier"
    assert purifier_device["tuya_category"] == "kj"
    assert (
        purifier_device["discovery_hints"]["classification_source"] == "tuya_category"
    )


def test_config_apply_sends_tuya_telemetry_and_event(mock_core, monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_plug_status)
    telemetry.core_base_url = mock_core.base_url
    event_client.core_base_url = mock_core.base_url

    payload = build_config_payload(
        config_id="tuya-plug-1",
        container_id="runtime-123",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.50",
            "tuya_device_id": "bf123",
            "local_key": "local-secret",
            "alias": "Desk Plug",
            "device_type": "plug",
        },
    )
    headers = build_runtime_headers(
        container_id="runtime-123", internal_token="secret-token"
    )

    with TestClient(app) as client:
        response = client.post("/config", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["config_id"] == "tuya-plug-1"

        wait_for(lambda: len(mock_core.telemetry_requests) >= 1)
        wait_for(lambda: len(mock_core.event_requests) >= 1)

    telemetry_request = assert_telemetry_sent(mock_core, device_id="tuya-plug-1")
    event_request = assert_event_sent(
        mock_core,
        device_id="tuya-plug-1",
        config_id="tuya-plug-1",
        event_type="tuya.config.applied",
    )

    telemetry_headers = {
        key.lower(): value for key, value in telemetry_request.headers.items()
    }
    event_headers = {key.lower(): value for key, value in event_request.headers.items()}

    assert telemetry_headers["x-container-id"] == "runtime-123"
    assert telemetry_headers["x-piphi-integration-token"] == "secret-token"
    assert event_headers["x-container-id"] == "runtime-123"
    assert event_headers["x-piphi-integration-token"] == "secret-token"
    assert telemetry_request.json_body["device_id"] == "tuya-plug-1"
    assert telemetry_request.json_body["metrics"]["power"] is True
    assert telemetry_request.json_body["metrics"]["power_w"] == 8.2
    assert telemetry_request.json_body["units"]["power"] == "bool"
    assert (
        event_request.json_body.get("event_type") or event_request.json_body.get("type")
    ) == "tuya.config.applied"


def test_config_apply_starts_background_poll_task(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_plug_status)

    payload = build_config_payload(
        config_id="tuya-poll-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.51",
            "tuya_device_id": "bfpoll",
            "local_key": "local-secret",
            "alias": "Polling Plug",
            "device_type": "plug",
            "poll_interval_seconds": 300,
        },
    )

    with TestClient(app) as client:
        response = client.post("/config", json=payload)
        assert response.status_code == 200
        assert "tuya-poll-1" in poll_tasks
        assert not poll_tasks["tuya-poll-1"].done()


def test_entities_reflect_configured_tuya_plug(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_plug_status)

    payload = build_config_payload(
        config_id="tuya-entities-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.52",
            "tuya_device_id": "bf456",
            "local_key": "local-secret",
            "alias": "Lamp Plug",
            "device_type": "plug",
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200

    entities_json = assert_entities_response(entities_response.json())
    entity = entities_json["entities"][0]
    assert entity["config_id"] == "tuya-entities-1"
    assert entity["name"] == "Lamp Plug"
    assert entity["device_type"] == "plug"
    assert entity["entity_type"] == "switch"
    assert "power_w" in entity["capabilities"]


def test_entities_reflect_configured_tuya_light(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_light_status)

    payload = build_config_payload(
        config_id="tuya-light-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.53",
            "tuya_device_id": "bflight",
            "local_key": "local-secret",
            "alias": "Hall Light",
            "device_type": "light",
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200

    entities_json = assert_entities_response(entities_response.json())
    entity = entities_json["entities"][0]
    assert entity["device_type"] == "light"
    assert entity["entity_type"] == "light"
    assert "brightness_percent" in entity["capabilities"]
    command_ids = {command["id"] for command in entity["available_commands"]}
    assert {"set_brightness", "set_color_temp", "set_color_rgb", "set_mode"}.issubset(
        command_ids
    )


def test_entities_reflect_configured_tuya_fan(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_fan_status)

    payload = build_config_payload(
        config_id="tuya-fan-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.55",
            "tuya_device_id": "bffan",
            "local_key": "local-secret",
            "alias": "Office Fan",
            "device_type": "fan",
            "fan_speed_dp": 3,
            "fan_speed_max": 3,
            "fan_mode_dp": 4,
            "fan_oscillate_dp": 5,
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200

    entities_json = assert_entities_response(entities_response.json())
    entity = entities_json["entities"][0]
    assert entity["device_type"] == "fan"
    assert entity["entity_type"] == "fan"
    assert "fan_speed_percent" in entity["capabilities"]
    command_ids = {command["id"] for command in entity["available_commands"]}
    assert {"set_fan_speed", "set_oscillate", "set_mode"}.issubset(command_ids)


def test_entities_reflect_configured_tuya_cover(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_cover_status)

    payload = build_config_payload(
        config_id="tuya-cover-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.56",
            "tuya_device_id": "bfcover",
            "local_key": "local-secret",
            "alias": "Office Blind",
            "device_type": "cover",
            "cover_control_dp": 1,
            "cover_position_dp": 2,
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200

    entities_json = assert_entities_response(entities_response.json())
    entity = entities_json["entities"][0]
    assert entity["device_type"] == "cover"
    assert entity["entity_type"] == "cover"
    assert "position_percent" in entity["capabilities"]
    command_ids = {command["id"] for command in entity["available_commands"]}
    assert {"open_cover", "close_cover", "stop_cover", "set_cover_position"}.issubset(
        command_ids
    )


def test_entities_reflect_configured_tuya_climate(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_climate_status)

    payload = build_config_payload(
        config_id="tuya-climate-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.57",
            "tuya_device_id": "bfclimate",
            "local_key": "local-secret",
            "alias": "Hall Thermostat",
            "device_type": "climate",
            "climate_target_temp_dp": 16,
            "climate_current_temp_dp": 24,
            "climate_mode_dp": 4,
            "climate_temp_scale": 10,
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200

    entities_json = assert_entities_response(entities_response.json())
    entity = entities_json["entities"][0]
    assert entity["device_type"] == "climate"
    assert entity["entity_type"] == "climate"
    assert "temperature_c" in entity["capabilities"]
    assert "target_temperature_c" in entity["capabilities"]
    command_ids = {command["id"] for command in entity["available_commands"]}
    assert {"set_temperature", "set_mode", "turn_on", "turn_off"}.issubset(command_ids)


def test_entities_reflect_configured_tuya_humidifier(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_humidifier_status)

    payload = build_config_payload(
        config_id="tuya-humidifier-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.58",
            "tuya_device_id": "bfhumid",
            "local_key": "local-secret",
            "alias": "Bedroom Humidifier",
            "device_type": "humidifier",
            "humidifier_target_humidity_dp": 103,
            "humidifier_current_humidity_dp": 104,
            "humidifier_mode_dp": 2,
            "humidifier_humidity_scale": 1,
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200

    entities_json = assert_entities_response(entities_response.json())
    entity = entities_json["entities"][0]
    assert entity["device_type"] == "humidifier"
    assert entity["entity_type"] == "humidifier"
    assert "humidity_percent" in entity["capabilities"]
    assert "target_humidity_percent" in entity["capabilities"]
    command_ids = {command["id"] for command in entity["available_commands"]}
    assert {"set_humidity", "set_mode", "turn_on", "turn_off"}.issubset(command_ids)


def test_entities_reflect_configured_tuya_air_purifier(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(
        state_module, "read_device_status", fake_read_air_purifier_status
    )

    payload = build_config_payload(
        config_id="tuya-purifier-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.59",
            "tuya_device_id": "bfpurifier",
            "local_key": "local-secret",
            "alias": "Bedroom Purifier",
            "device_type": "air_purifier",
            "purifier_speed_dp": 4,
            "purifier_speed_max": 3,
            "purifier_mode_dp": 2,
            "purifier_aqi_dp": 22,
            "purifier_aqi_scale": 1,
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        entities_response = client.get("/entities")
        assert entities_response.status_code == 200

    entities_json = assert_entities_response(entities_response.json())
    entity = entities_json["entities"][0]
    assert entity["device_type"] == "air_purifier"
    assert entity["device_class"] == "air_purifier"
    assert entity["entity_type"] == "air_purifier"
    assert "fan_speed_percent" in entity["capabilities"]
    assert "air_quality_index" in entity["capabilities"]
    command_ids = {command["id"] for command in entity["available_commands"]}
    assert {"set_fan_speed", "set_mode", "turn_on", "turn_off"}.issubset(command_ids)


def test_health_diagnostics_and_state_redact_runtime_details(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_plug_status)

    payload = build_config_payload(
        config_id="tuya-health-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.62",
            "tuya_device_id": "bfhealth",
            "local_key": "super-secret",
            "alias": "Health Plug",
            "device_type": "plug",
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        health_response = client.get("/health")
        diagnostics_response = client.get("/diagnostics")
        state_response = client.get("/state")

    assert health_response.status_code == 200
    health_body = health_response.json()
    assert health_body["metadata"]["active_configs"] == 1
    assert health_body["metadata"]["healthy_configs"] == 1
    assert health_body["metadata"]["poll_task_count"] == 1

    assert diagnostics_response.status_code == 200
    diagnostics_body = diagnostics_response.json()
    assert diagnostics_body["diagnostics"]["poll_task_count"] == 1
    assert diagnostics_body["diagnostics"]["persistent_session_count"] == 1
    assert diagnostics_body["diagnostics"]["devices"][0]["config_id"] == "tuya-health-1"
    assert diagnostics_body["diagnostics"]["devices"][0]["connected"] is True

    assert state_response.status_code == 200
    state_body = state_response.json()
    assert state_body["summary"]["poll_task_count"] == 1
    assert (
        state_body["entries"]["tuya-health-1"]["config"]["local_key"]
        == "***redacted***"
    )


def test_config_apply_fails_fast_when_initial_validation_fails(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_failure)

    payload = build_config_payload(
        config_id="tuya-invalid-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.63",
            "tuya_device_id": "bfinvalid",
            "local_key": "wrong-secret",
            "alias": "Bad Plug",
            "device_type": "plug",
        },
    )

    with TestClient(app) as client:
        response = client.post("/config", json=payload)

    body = response.json()
    assert response.status_code == 502
    assert body["ok"] is False
    assert body["error"]["type"] == "tuya_client_error"
    assert "Config validation failed" in body["error"]["message"]
    assert "tuya-invalid-1" not in registry.ids()


def test_config_rejects_duplicate_tuya_identity(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_plug_status)

    first_payload = build_config_payload(
        config_id="tuya-dup-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.64",
            "tuya_device_id": "bfdupdevice",
            "local_key": "secret-one",
            "alias": "Original Plug",
            "device_type": "plug",
        },
    )
    second_payload = build_config_payload(
        config_id="tuya-dup-2",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.65",
            "tuya_device_id": "bfdupdevice",
            "local_key": "secret-two",
            "alias": "Duplicate Plug",
            "device_type": "plug",
        },
    )

    with TestClient(app) as client:
        first_response = client.post("/config", json=first_payload)
        assert first_response.status_code == 200

        second_response = client.post("/config", json=second_payload)

    body = second_response.json()
    assert second_response.status_code == 409
    assert body["ok"] is False
    assert "already configured" in body["error"]["message"]
    assert registry.ids() == ["tuya-dup-1"]


def test_discover_rejects_partial_cloud_credentials() -> None:
    reset_runtime_state()
    with TestClient(app) as client:
        response = client.post(
            "/discover",
            json={
                "inputs": {
                    "api_region": "us",
                    "api_key": "key-only",
                }
            },
        )

    assert response.status_code == 422


def test_discover_rejects_invalid_scan_seconds() -> None:
    reset_runtime_state()
    with TestClient(app) as client:
        response = client.post(
            "/discover",
            json={"inputs": {"lan_scan": True, "scan_seconds": 0}},
        )

    assert response.status_code == 422


def test_command_turn_on_returns_refreshed_state(monkeypatch) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_plug_status)

    async def fake_execute_command_for_entry(entry, command_name, args=None):
        return {
            "result": {"success": True, "command": command_name},
            "state": {
                "connected": True,
                "power": True,
                "config_id": entry["config_id"],
            },
        }

    command_module = importlib.import_module("piphi_network_tuya.routes.commands")
    monkeypatch.setattr(
        command_module, "execute_command_for_entry", fake_execute_command_for_entry
    )

    payload = build_config_payload(
        config_id="tuya-command-1",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.54",
            "tuya_device_id": "bf789",
            "local_key": "local-secret",
            "alias": "Office Plug",
            "device_type": "plug",
        },
    )

    with TestClient(app) as client:
        config_response = client.post("/config", json=payload)
        assert config_response.status_code == 200

        command_response = client.post(
            "/command",
            json={
                "command": "turn_on",
                "config_id": "tuya-command-1",
                "device_id": "tuya-command-1",
            },
        )

    body = command_response.json()
    assert command_response.status_code == 200
    assert body["ok"] is True
    assert body["command"] == "turn_on"
    assert body["state"]["power"] is True


def test_command_replays_idempotency_key_without_repeating_device_effect(
    monkeypatch,
) -> None:
    reset_runtime_state()
    calls = 0

    async def fake_execute_command_for_entry(entry, command_name, args=None):
        nonlocal calls
        calls += 1
        return {
            "result": {"success": True, "command": command_name},
            "state": {
                "connected": True,
                "power": True,
                "config_id": entry["config_id"],
            },
        }

    command_module = importlib.import_module("piphi_network_tuya.routes.commands")
    monkeypatch.setattr(
        command_module, "execute_command_for_entry", fake_execute_command_for_entry
    )
    registry.set(
        "tuya-idempotency-1",
        {
            "config_id": "tuya-idempotency-1",
            "device_id": "tuya-idempotency-1",
        },
    )
    headers = {"X-PiPhi-Idempotency-Key": "tuya-action-idempotency-1"}
    payload = {
        "command": "turn_on",
        "config_id": "tuya-idempotency-1",
        "device_id": "tuya-idempotency-1",
    }

    with TestClient(app) as client:
        first = client.post("/command", json=payload, headers=headers)
        replay = client.post("/command", json=payload, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert calls == 1


def test_config_sync_replaces_tuya_device_and_uses_testkit_snapshot(
    mock_core, monkeypatch
) -> None:
    reset_runtime_state()
    monkeypatch.setattr(state_module, "read_device_status", fake_read_plug_status)
    telemetry.core_base_url = mock_core.base_url
    event_client.core_base_url = mock_core.base_url

    old_payload = build_config_payload(
        config_id="tuya-old",
        container_id="runtime-123",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.60",
            "tuya_device_id": "old-device",
            "local_key": "old-key",
            "alias": "Old Plug",
            "device_type": "plug",
        },
    )
    new_payload = build_config_payload(
        config_id="tuya-new",
        container_id="runtime-123",
        integration_id="piphi-network-tuya",
        extra={
            "host": "10.0.0.61",
            "tuya_device_id": "new-device",
            "local_key": "new-key",
            "alias": "New Plug",
            "device_type": "plug",
        },
    )
    snapshot = build_config_snapshot(
        configs=[new_payload],
        container_id="runtime-123",
        integration_id="piphi-network-tuya",
        generation=7,
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
        wait_for(lambda: len(mock_core.event_requests) >= 1)
        assert "tuya-new" in poll_tasks

    sync_json = sync_response.json()
    assert sync_json["applied"] == ["tuya-new"]
    assert sync_json["removed"] == ["tuya-old"]
    assert sync_json["active_config_ids"] == ["tuya-new"]
    assert sync_json["generation"] == 7

    telemetry_request = assert_telemetry_sent(mock_core, device_id="tuya-new")
    assert telemetry_request.json_body["config_id"] == "tuya-new"
