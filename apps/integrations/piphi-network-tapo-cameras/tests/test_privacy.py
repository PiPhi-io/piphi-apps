from __future__ import annotations

import json

import httpx
import pytest
from fakes import FakeTapoClient, camera_snapshot
from pydantic import SecretStr

from piphi_network_tapo_cameras.main import app
from piphi_network_tapo_cameras.schemas import DeviceConfig
from piphi_network_tapo_cameras.state import apply_config, registry, runtime_data


@pytest.mark.anyio
async def test_credentials_and_transport_identity_do_not_escape_public_surfaces() -> None:
    password = "password-canary-5c12"
    username = "username-canary@example.invalid"
    host = "192.0.2.99"
    runtime_data.connector = lambda **_: _return(
        FakeTapoClient(camera_snapshot(hardware_id="opaque-fixture-id"))
    )
    await apply_config(
        DeviceConfig(
            id="front",
            host=host,
            username=username,
            password=SecretStr(password),
        )
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payloads = [
            registry.entries,
            (await client.get("/state")).json(),
            (await client.get("/entities")).json(),
            (await client.get("/events")).json(),
            (await client.get("/diagnostics")).json(),
        ]
    serialized = json.dumps(payloads, default=str)
    assert password not in serialized
    assert username not in serialized
    assert host not in serialized
    assert "raw-device-id" not in serialized


async def _return(value):
    return value
