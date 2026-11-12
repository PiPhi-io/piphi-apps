from __future__ import annotations

import httpx
import pytest

from piphi_network_kaiterra_api import state
from piphi_network_kaiterra_api.main import app
from piphi_network_kaiterra_api.routes import commands as command_routes


@pytest.mark.anyio
async def test_command_accepts_automation_runtime_contract() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/command",
            json={
                "contract_version": "automation.runtime.command.v1",
                "command": "refresh_readings",
                "target": {
                    "config_id": "kaiterra-device",
                    "device_id": "kaiterra-device",
                },
                "params": {"force": True},
                "capability": "device.refresh",
                "capability_requirements": ["device.refresh"],
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["command"] == "refresh"
    assert body["contract_version"] == "automation.runtime.command.v1"
    assert body["config_id"] == "kaiterra-device"
    assert body["params"] == {"force": True}


@pytest.mark.anyio
async def test_command_rejects_unsupported_capability() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/command",
            json={
                "command": "refresh",
                "target": {"device_id": "kaiterra-device"},
                "capability": "switch.power",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "unsupported_capability"


@pytest.mark.anyio
async def test_command_replays_without_repeating_cloud_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refreshes = 0

    async def fake_refresh_entry(entry):
        nonlocal refreshes
        refreshes += 1
        return {"device_udid": entry["device_udid"], "temperature_c": 22.0}

    monkeypatch.setattr(command_routes, "refresh_entry", fake_refresh_entry)
    state.registry.set(
        "kaiterra-idempotent",
        {
            "config_id": "kaiterra-idempotent",
            "device_id": "kaiterra-idempotent",
            "device_udid": "kaiterra-idempotent",
        },
    )
    headers = {"X-PiPhi-Idempotency-Key": "kaiterra-refresh-idempotency-1"}
    payload = {
        "command": "refresh",
        "config_id": "kaiterra-idempotent",
        "device_id": "kaiterra-idempotent",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        first = await client.post("/command", json=payload, headers=headers)
        replay = await client.post("/command", json=payload, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert refreshes == 1
    state.registry.remove("kaiterra-idempotent")
