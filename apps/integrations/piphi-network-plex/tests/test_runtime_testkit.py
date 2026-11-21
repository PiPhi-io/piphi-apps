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

from piphi_network_plex.main import app
from piphi_network_plex.plex_client import PlexServer
from piphi_network_plex.state import events, plex_service, telemetry


async def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for Runtime SDK delivery")


class TestKitPlexClient:
    async def discover(self, token: str, **_kwargs):
        return [PlexServer("test-server", "Test Plex", "http://plex:32400", token)]

    async def request(self, _server, path: str, **_kwargs):
        if path == "/status/sessions":
            return {"MediaContainer": {"Metadata": []}}
        return {"MediaContainer": {"Metadata": []}}

    @staticmethod
    def metadata(payload):
        return payload.get("MediaContainer", {}).get("Metadata", [])


@pytest.mark.anyio
async def test_testkit_captures_telemetry_entities_and_command() -> None:
    mock_core = MockCoreServer()
    original_client = plex_service.client
    original_telemetry_url = telemetry.core_base_url
    original_event_url = events.core_base_url
    plex_service.client = TestKitPlexClient()
    telemetry.core_base_url = mock_core.base_url
    events.core_base_url = mock_core.base_url
    payload = build_config_payload(
        config_id="plex-test",
        device_id="plex-test-server",
        container_id="plex-container",
        integration_id="piphi-network-plex",
        extra={"token": "test-token", "poll_interval_seconds": 3600},
    )
    headers = build_runtime_headers(
        container_id="plex-container", internal_token="test-runtime-token"
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            configured = await client.post("/config", json=payload, headers=headers)
            assert configured.status_code == 200, configured.text
            await wait_for(lambda: bool(mock_core.telemetry_requests))
            telemetry_request = mock_core.assert_telemetry_sent(device_id="plex-test-server")
            assert telemetry_request.json_body["metrics"]["server_count"] == 1

            entities = assert_entities_response((await client.get("/entities")).json())["entities"]
            assert entities[0]["device_class"] == "media_server"

            refreshed = await client.post(
                "/command",
                headers=headers,
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "refresh",
                    "target": {
                        "config_id": "plex-test",
                        "device_id": "plex-test-server",
                    },
                    "params": {},
                    "capability": "refresh",
                    "capability_requirements": ["refresh"],
                },
            )
            assert refreshed.status_code == 200, refreshed.text
            assert refreshed.json()["result"]["available"] is True
    finally:
        await asyncio.sleep(0.05)
        plex_service.client = original_client
        telemetry.core_base_url = original_telemetry_url
        events.core_base_url = original_event_url
        mock_core.shutdown()
