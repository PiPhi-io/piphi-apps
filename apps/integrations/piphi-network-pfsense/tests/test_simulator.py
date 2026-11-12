from __future__ import annotations

from types import SimpleNamespace

import pytest

from piphi_network_pfsense.schemas import DeviceConfig
from piphi_network_pfsense.service import (
    ActiveFirewall,
    PfSenseRuntimeService,
    default_client_factory,
    snapshot_to_state,
)
from piphi_network_pfsense.simulator import SimulatedPfSenseClient


def simulated_config(**overrides: object) -> DeviceConfig:
    values = {
        "id": "pfsense-simulator",
        "config_id": "pfsense-simulator",
        "simulation_mode": True,
    }
    values.update(overrides)
    return DeviceConfig.model_validate(values)


def test_simulation_mode_does_not_require_live_credentials() -> None:
    config = simulated_config()
    assert config.base_url == "simulator://pfsense"
    assert isinstance(default_client_factory(config), SimulatedPfSenseClient)


def test_live_mode_still_requires_host_and_api_key() -> None:
    with pytest.raises(ValueError, match="host is required"):
        DeviceConfig(id="live")
    with pytest.raises(ValueError, match="api_key is required"):
        DeviceConfig(id="live", host="pfsense.local")


@pytest.mark.anyio
async def test_simulator_exercises_live_projection_and_actions() -> None:
    config = simulated_config(
        enable_diagnostic_ping=True,
        allowed_ping_hosts=["1.1.1.1"],
        enable_service_restart=True,
        enable_service_start=True,
        allowed_services=["unbound"],
        enable_wake_on_lan=True,
        wake_on_lan_targets=[
            {
                "id": "office-pc",
                "label": "Office PC",
                "interface": "lan",
                "mac_addr": "02:00:00:00:00:02",
            }
        ],
    )
    client = SimulatedPfSenseClient(config)
    state = snapshot_to_state(await client.read_snapshot())
    assert state["connected"] is True
    assert state["interfaces_up"] == 2
    assert state["gateways_offline"] == 0
    assert state["vpn_tunnels_up"] == 2
    assert state["clients_online"] == 2
    assert state["certificates_expiring"] == 1
    assert state["ha_enabled"] is True
    assert state["security_log_count"] == 2

    service = PfSenseRuntimeService(
        registry=SimpleNamespace(),
        runtime=SimpleNamespace(),
        telemetry=SimpleNamespace(),
    )
    service._active["pfsense-simulator"] = ActiveFirewall(
        config=config,
        entry={"config_id": "pfsense-simulator", "device_id": "pfsense-simulator"},
        client=client,
    )
    assert (
        await service.diagnostic_ping("pfsense-simulator", host="1.1.1.1", count=2)
    )["result_code"] == 0
    assert (await service.restart_service("pfsense-simulator", service_name="unbound"))[
        "simulated"
    ] is True
    assert (await service.start_service("pfsense-simulator", service_name="unbound"))[
        "simulated"
    ] is True
    assert (await service.wake_on_lan("pfsense-simulator", target_id="office-pc"))[
        "sent"
    ] is True
