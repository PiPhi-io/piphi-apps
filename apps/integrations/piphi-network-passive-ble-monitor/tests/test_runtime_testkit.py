from __future__ import annotations

import httpx
import pytest
from piphi_runtime_testkit_python import assert_entities_response, build_config_payload, build_runtime_headers

from piphi_network_passive_ble_monitor import state
from piphi_network_passive_ble_monitor.main import app


@pytest.mark.anyio
async def test_testkit_configuration_identity_and_entities_flow(monkeypatch) -> None:
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    payload = build_config_payload(
        config_id="testkit-config",
        device_id="testkit-device",
        container_id="ble-runtime-1",
        integration_id="piphi-network-passive-ble-monitor",
        extra={
            "gateway_url": "https://gateway.test",
            "gateway_token": "gateway-secret",
            "device_handle": "ble_00000000000000000000000000000004",
            "alias": "TestKit BTHome sensor",
        },
    )
    headers = build_runtime_headers(container_id="ble-runtime-1", internal_token="runtime-secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            configured = await client.post("/config", json=payload, headers=headers)
            assert configured.status_code == 200
            entities = assert_entities_response((await client.get("/entities", headers=headers)).json())
            entity = next(item for item in entities["entities"] if item["config_id"] == "testkit-config")
            assert entity["device_id"] == "testkit-device"
            assert "sensor_available" in entity["capabilities"]
            assert "gateway-secret" not in str(entities)
        finally:
            await client.post("/deconfigure/testkit-config", headers=headers)
