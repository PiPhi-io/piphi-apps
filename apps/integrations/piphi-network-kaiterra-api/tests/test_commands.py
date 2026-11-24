from __future__ import annotations

import httpx
import pytest

from piphi_network_kaiterra_api import state
from piphi_network_kaiterra_api.main import app
from piphi_network_kaiterra_api.routes import commands as command_routes
from conftest import RUNTIME_HEADERS


def _entry(config_id: str = "kaiterra-device") -> dict[str, str]:
    return {
        "config_id": config_id,
        "device_id": f"piphi-network-kaiterra-api:{config_id}",
        "device_ref": config_id,
    }


@pytest.mark.anyio
async def test_command_requires_runtime_auth_and_exact_target(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_refresh(entry):
        return {"device_ref": entry["device_ref"], "temperature_c": 22.0}

    monkeypatch.setattr(command_routes, "refresh_entry", fake_refresh)
    state.registry.set("kaiterra-device", _entry())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthorized = await client.post("/command", json={"command": "refresh", "config_id": "kaiterra-device"})
        response = await client.post(
            "/command",
            headers=RUNTIME_HEADERS,
            json={
                "contract_version": "automation.runtime.command.v1",
                "command": "refresh_readings",
                "target": {"config_id": "kaiterra-device"},
                "params": {},
                "capability": "device.refresh",
            },
        )
    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["command"] == "refresh"
    assert response.json()["config_id"] == "kaiterra-device"


@pytest.mark.anyio
async def test_command_rejects_unsupported_capability() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/command",
            headers=RUNTIME_HEADERS,
            json={"command": "refresh", "config_id": "x", "capability": "switch.power"},
        )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "unsupported_capability"


@pytest.mark.anyio
async def test_command_replays_without_repeating_cloud_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    refreshes = 0

    async def fake_refresh_entry(entry):
        nonlocal refreshes
        refreshes += 1
        return {"device_ref": entry["device_ref"], "temperature_c": 22.0}

    monkeypatch.setattr(command_routes, "refresh_entry", fake_refresh_entry)
    state.registry.set("kaiterra-idempotent", _entry("kaiterra-idempotent"))
    headers = {
        **RUNTIME_HEADERS,
        "X-PiPhi-Idempotency-Key": "kaiterra-refresh-idempotency-v016",
    }
    payload = {"command": "refresh", "config_id": "kaiterra-idempotent"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/command", json=payload, headers=headers)
        replay = await client.post("/command", json=payload, headers=headers)
    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert refreshes == 1
