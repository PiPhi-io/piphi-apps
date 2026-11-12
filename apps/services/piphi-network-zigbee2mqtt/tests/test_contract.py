from __future__ import annotations

from piphi_network_zigbee2mqtt.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_zigbee2mqtt.main import app


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
        "/v1/snapshot",
        "/v1/adapters",
        "/v1/config/render",
        "/v1/config/write",
        "/v1/apply",
        "/v1/supervisor/status",
        "/v1/supervisor/start",
        "/v1/supervisor/stop",
        "/v1/supervisor/restart",
        "/v1/supervisor/logs",
        "/v1/prerequisites",
        "/v1/mqtt/check",
    ]:
        assert path in routes

    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert "refresh" in COMMANDS
