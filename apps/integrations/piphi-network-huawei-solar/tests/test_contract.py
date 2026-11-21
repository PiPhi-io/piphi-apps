from __future__ import annotations

from piphi_network_huawei_solar.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_huawei_solar.main import app
from piphi_network_huawei_solar.settings import DEFAULT_PORT, runtime_port


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


def test_runtime_port_falls_back_for_invalid_environment(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "invalid")
    assert runtime_port() == DEFAULT_PORT
    monkeypatch.setenv("PORT", "5213")
    assert runtime_port() == 5213
