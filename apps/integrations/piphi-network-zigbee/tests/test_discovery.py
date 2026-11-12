from __future__ import annotations

import httpx
import pytest

from piphi_network_zigbee.main import app


@pytest.mark.anyio
async def test_discovery_accepts_zigbee2mqtt_device_input() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/discover",
            json={
                "inputs": {
                    "device": {
                        "friendly_name": "office_contact",
                        "ieee_address": "0x00158d0000000002",
                        "definition": {
                            "model": "MCCGQ11LM",
                            "vendor": "Aqara",
                            "exposes": [{"property": "contact"}],
                        },
                    }
                }
            },
        )

    assert response.status_code == 200
    devices = response.json()["devices"]
    assert devices[0]["friendly_name"] == "office_contact"
    assert devices[0]["vendor"] == "Aqara"
    assert "contact_open" in devices[0]["capabilities"]
