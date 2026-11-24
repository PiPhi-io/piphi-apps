from __future__ import annotations

import httpx
import pytest

from piphi_network_openepaperlink import state
from piphi_network_openepaperlink.ap import AccessPointSnapshot, TagObservation
from piphi_network_openepaperlink.main import app


@pytest.mark.anyio
async def test_authenticated_runtime_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-secret")

    async def fake_fetch(_host: str) -> AccessPointSnapshot:
        return AccessPointSnapshot((TagObservation("0011223344556677", 1),))

    monkeypatch.setattr(state, "snapshot_fetcher", fake_fetch)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    headers = {"X-PiPhi-Integration-Token": "runtime-secret"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runtime") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/entities")).status_code == 401
        configured = await client.post(
            "/config",
            headers=headers,
            json={"id": "ap-one", "host": "192.168.1.25", "alias": "Kitchen"},
        )
        assert configured.status_code == 200
        entities = (await client.get("/entities", headers=headers)).json()["entities"]
        assert len(entities) == 2
        ap_entity = next(entity for entity in entities if entity["entity_type"] == "access_point")
        tag_entity = next(entity for entity in entities if entity["entity_type"] == "display_tag")
        assert tag_entity["parent_device_id"] == ap_entity["device_id"]
        assert "0011223344556677" not in str(entities)
        command = await client.post(
            "/command",
            headers=headers,
            json={
                "contract_version": "automation.runtime.command.v1",
                "command": "refresh",
                "device_id": ap_entity["device_id"],
                "config_id": "ap-one",
                "params": {},
                "capability": "device.refresh",
            },
        )
        assert command.status_code == 200
        assert command.json()["status"] == "success"
        diagnostics = (await client.get("/diagnostics", headers=headers)).json()
        assert "ap-one" not in str(diagnostics)
        assert (await client.post("/deconfigure/ap-one", headers=headers)).status_code == 200
