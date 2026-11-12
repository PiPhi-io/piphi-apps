from __future__ import annotations

import httpx
import pytest

from piphi_network_pfsense.main import app
from piphi_network_pfsense.state import pfsense_service, registry


@pytest.mark.anyio
async def test_diagnostic_ping_dispatches_through_runtime_command(monkeypatch) -> None:
    calls: list[tuple[str, str, int]] = []

    async def diagnostic_ping(config_id: str, *, host: str, count: int):
        calls.append((config_id, host, count))
        return {"result_code": 0, "output": "reply"}

    monkeypatch.setattr(pfsense_service, "diagnostic_ping", diagnostic_ping)
    registry.set(
        "firewall-action",
        {
            "config_id": "firewall-action",
            "device_id": "firewall-action",
            "integration_id": "piphi-network-pfsense",
        },
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/command",
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "diagnostic_ping",
                    "target": {
                        "config_id": "firewall-action",
                        "device_id": "firewall-action",
                    },
                    "params": {"host": "1.1.1.1", "count": 2},
                    "capability": "action.diagnostic_ping",
                    "capability_requirements": ["action.diagnostic_ping"],
                },
            )
    finally:
        registry.remove("firewall-action")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["result_code"] == 0
    assert calls == [("firewall-action", "1.1.1.1", 2)]
