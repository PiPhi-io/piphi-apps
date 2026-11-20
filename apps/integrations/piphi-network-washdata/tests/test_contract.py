from piphi_network_washdata.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_washdata.main import app


def test_runtime_implements_monitoring_contract_routes() -> None:
    routes = set(app.openapi()["paths"])
    assert {
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
    } <= routes
    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert set(COMMANDS) == {"refresh"}


def test_power_control_is_not_in_public_contract() -> None:
    schema = app.openapi()
    assert "set_power" not in repr(schema)
    assert "cut_appliance_power" not in repr(schema)
