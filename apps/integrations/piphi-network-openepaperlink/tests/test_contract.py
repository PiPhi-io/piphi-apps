from __future__ import annotations

from piphi_network_openepaperlink.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_openepaperlink.main import app


def test_runtime_implements_only_the_supported_contract_routes() -> None:
    routes = set(app.openapi()["paths"])
    assert routes == {
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
        "/command",
    }
    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert set(COMMANDS) == {"refresh"}
    assert not any("example" in route or "telemetry" in route for route in routes)
