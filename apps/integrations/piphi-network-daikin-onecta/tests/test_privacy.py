from __future__ import annotations

import json

import httpx
import pytest
from test_normalization import provider_payload

from piphi_network_daikin_onecta import state
from piphi_network_daikin_onecta.main import app
from piphi_network_daikin_onecta.onecta import AccountSnapshot, Quota
from piphi_network_daikin_onecta.schemas import DeviceConfig


class PrivacyClient:
    def __init__(self, _token: str) -> None:
        pass

    async def fetch_devices(self) -> AccountSnapshot:
        return AccountSnapshot(provider_payload(), Quota(minute_remaining=4))

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_oauth_and_provider_identities_do_not_escape_surfaces(
    monkeypatch,
) -> None:
    token = "access-token-canary-5c12"
    subject = "oauth-subject-canary@example.invalid"
    monkeypatch.setattr(state.runtime_data, "client_factory", PrivacyClient)
    await state.apply_config(
        DeviceConfig(id="privacy", oauth_subject=subject, access_token=token)
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payloads = [
            state.registry.entries,
            (await client.get("/state")).json(),
            (await client.get("/entities")).json(),
            (await client.get("/events")).json(),
            (await client.get("/diagnostics")).json(),
        ]
    serialized = json.dumps(payloads, default=str)
    assert token not in serialized
    assert subject not in serialized
    assert "gateway-private-id" not in serialized
    assert "climateControl" not in serialized
    await state.remove_config("privacy")
