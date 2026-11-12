from __future__ import annotations

import asyncio

import httpx
import pytest
from piphi_runtime_testkit_python import (
    MockCoreServer,
    assert_entities_response,
    build_config_payload,
    build_runtime_headers,
)

from piphi_network_pfsense.main import app
from piphi_network_pfsense.pfsense_client import PfSenseSnapshot
from piphi_network_pfsense.state import (
    pfsense_service,
    registry,
    remove_config,
    starter,
    telemetry,
)


async def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for Runtime SDK delivery")


class SequencedPfSenseClient:
    def __init__(self) -> None:
        self._snapshots = [
            PfSenseSnapshot(
                system={"platform": "pfSense", "cpu_usage": 11, "mem_usage": 22},
                gateways=[{"name": "WAN", "status": "online", "delay": 8}],
                dhcp_leases=[
                    {
                        "mac": "aa:bb:cc:dd:ee:ff",
                        "ip": "192.0.2.10",
                        "hostname": "office-pc",
                        "online_status": "online",
                    }
                ],
                arp_entries=[
                    {
                        "mac_address": "aa:bb:cc:dd:ee:ff",
                        "ip_address": "192.0.2.10",
                        "interface": "lan",
                    }
                ],
            ),
            PfSenseSnapshot(
                system={"platform": "pfSense", "cpu_usage": 12, "mem_usage": 23},
                gateways=[{"name": "WAN", "status": "down", "delay": 0}],
                dhcp_leases=[
                    {
                        "mac": "aa:bb:cc:dd:ee:ff",
                        "ip": "192.0.2.10",
                        "hostname": "office-pc",
                        "online_status": "online",
                    }
                ],
            ),
        ]
        self._index = 0

    async def read_snapshot(self) -> PfSenseSnapshot:
        snapshot = self._snapshots[min(self._index, len(self._snapshots) - 1)]
        self._index += 1
        return snapshot

    async def diagnostic_ping(self, host: str, *, count: int) -> dict:
        return {"host": host, "count": count}

    async def restart_service(self, service_name: str) -> dict:
        return {"name": service_name, "status": True}

    async def start_service(self, service_name: str) -> dict:
        return {"name": service_name, "status": True}

    async def wake_on_lan(self, *, interface: str, mac_addr: str) -> dict:
        return {"interface": interface, "mac_addr": mac_addr}

    async def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_testkit_captures_runtime_telemetry_entities_and_transition_events(
    monkeypatch,
) -> None:
    mock_core = MockCoreServer()
    previous_telemetry_url = telemetry.core_base_url
    previous_event_url = starter.event_client.core_base_url
    monkeypatch.setattr(
        pfsense_service, "client_factory", lambda _config: SequencedPfSenseClient()
    )
    telemetry.core_base_url = mock_core.base_url
    starter.event_client.core_base_url = mock_core.base_url

    payload = build_config_payload(
        config_id="testkit-firewall",
        device_id="testkit-firewall",
        container_id="testkit-container",
        integration_id="piphi-network-pfsense",
        extra={
            "host": "pfsense.test",
            "api_key": "fake-test-key",
            "collect_client_inventory": True,
        },
    )
    headers = build_runtime_headers(
        container_id="testkit-container", internal_token="fake-runtime-token"
    )
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            configured = await client.post("/config", json=payload, headers=headers)
            assert configured.status_code == 200
            await wait_for(lambda: bool(mock_core.telemetry_requests))

            telemetry_request = mock_core.assert_telemetry_sent(
                device_id="testkit-firewall"
            )
            assert telemetry_request.json_body["config_id"] == "testkit-firewall"
            assert telemetry_request.json_body["metrics"]["cpu_usage_percent"] == 11

            entities_response = await client.get("/entities")
            assert entities_response.status_code == 200
            entities = assert_entities_response(entities_response.json())["entities"]
            assert any(
                entity["device_id"] == "testkit-firewall:client:aa:bb:cc:dd:ee:ff"
                for entity in entities
            )

            refreshed = await client.post(
                "/command",
                headers=headers,
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "refresh",
                    "target": {
                        "config_id": "testkit-firewall",
                        "device_id": "testkit-firewall",
                    },
                    "params": {},
                    "capability": "device.refresh",
                    "capability_requirements": ["device.refresh"],
                },
            )
            assert refreshed.status_code == 200
            await wait_for(lambda: bool(mock_core.event_requests))

            event_request = mock_core.assert_event_sent(
                device_id="testkit-firewall:gateway:WAN",
                config_id="testkit-firewall",
                event_type="network.gateway.offline",
            )
            event_headers = {
                key.lower(): value for key, value in event_request.headers.items()
            }
            assert event_headers["x-container-id"] == "testkit-container"
            assert event_headers["x-piphi-integration-token"] == "fake-runtime-token"
    finally:
        telemetry.core_base_url = previous_telemetry_url
        starter.event_client.core_base_url = previous_event_url
        if registry.get("testkit-firewall") is not None:
            await remove_config("testkit-firewall")
        mock_core.shutdown()
