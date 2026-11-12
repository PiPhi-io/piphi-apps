from __future__ import annotations

from piphi_network_pfsense.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_pfsense.main import app


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

    assert REQUIRED_ENDPOINTS == [
        "health",
        "entities",
        "command",
        "config",
        "ui_config",
    ]
    assert "refresh" in COMMANDS
    assert "diagnostic_ping" in COMMANDS
    assert "restart_service" in COMMANDS
    assert "start_service" in COMMANDS
    assert "wake_on_lan" in COMMANDS
