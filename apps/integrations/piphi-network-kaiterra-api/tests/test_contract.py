from __future__ import annotations

from piphi_network_kaiterra_api.contract import CAPABILITIES, COMMANDS, CONFIG_SCHEMA, REQUIRED_ENDPOINTS
from piphi_network_kaiterra_api.kaiterra import normalize_latest_reading
from piphi_network_kaiterra_api.main import app


def test_runtime_implements_contract_routes() -> None:
    routes = set(app.openapi()["paths"])
    for path in [
        "/health",
        "/diagnostics",
        "/discover",
        "/config",
        "/config/sync",
        "/deconfigure",
        "/deconfigure/{config_id}",
        "/ui-config",
        "/entities",
        "/state",
        "/contract",
        "/events",
        "/events/device/{config_id}/example",
        "/telemetry/example",
        "/telemetry/device/{config_id}/example",
        "/command",
    ]:
        assert path in routes

    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert "refresh" in COMMANDS


def test_kaiterra_contract_exposes_air_quality_capabilities() -> None:
    for capability_id in [
        "temperature_c",
        "humidity_percent",
        "co2_ppm",
        "pm25_ug_m3",
        "tvoc_ppb",
        "ozone_ppb",
    ]:
        assert capability_id in CAPABILITIES

    required = CONFIG_SCHEMA["schema"]["required"]
    assert "device_udid" in required
    assert "api_key" in required


def test_normalize_latest_reading_maps_kaiterra_parameters() -> None:
    metrics, units, latest_timestamp = normalize_latest_reading(
        {
            "data": [
                {
                    "param": "rtemp",
                    "units": "C",
                    "points": [{"ts": "2026-05-10T12:00:00Z", "value": 21.2}],
                },
                {
                    "param": "rpm25c",
                    "units": "ug/m3",
                    "points": [{"ts": "2026-05-10T12:00:00Z", "value": 8.4}],
                },
                {
                    "param": "rco2",
                    "units": "ppm",
                    "points": [{"ts": "2026-05-10T12:01:00Z", "value": 612}],
                },
            ]
        }
    )

    assert metrics == {
        "temperature_c": 21.2,
        "pm25_ug_m3": 8.4,
        "co2_ppm": 612,
    }
    assert units["pm25_ug_m3"] == "ug/m3"
    assert latest_timestamp == "2026-05-10T12:01:00Z"
