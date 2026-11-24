from __future__ import annotations

import asyncio

import httpx
import pytest
from piphi_runtime_kit_python import schedule_event_delivery
from piphi_runtime_testkit_python import (
    MockCoreServer,
    assert_entities_response,
    build_config_payload,
    build_runtime_headers,
)

from piphi_network_openepaperlink import state
from piphi_network_openepaperlink.ap import AccessPointSnapshot, TagObservation
from piphi_network_openepaperlink.main import app


async def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for Runtime SDK delivery")


@pytest.mark.anyio
async def test_testkit_captures_config_entities_telemetry_events_and_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_core = MockCoreServer()
    original_telemetry_url = state.telemetry.core_base_url
    original_event_url = state.events.core_base_url
    snapshots = [
        AccessPointSnapshot(
            (
                TagObservation("0011223344556677", 2),
                TagObservation("8899aabbccddeeff", 0),
            )
        ),
        AccessPointSnapshot((TagObservation("0011223344556677", 0),)),
    ]

    async def fake_fetch(_host: str) -> AccessPointSnapshot:
        return snapshots.pop(0)

    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "test-runtime-token")
    monkeypatch.setattr(state, "snapshot_fetcher", fake_fetch)
    monkeypatch.setattr(state, "event_scheduler", schedule_event_delivery)
    state.telemetry.core_base_url = mock_core.base_url
    state.events.core_base_url = mock_core.base_url
    payload = build_config_payload(
        config_id="oepl-test",
        device_id="core-proposed-device-id",
        container_id="oepl-container",
        integration_id="piphi-network-openepaperlink",
        extra={"host": "192.168.1.25", "poll_interval_seconds": 3600},
    )
    headers = build_runtime_headers(
        container_id="oepl-container", internal_token="test-runtime-token"
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://runtime"
        ) as client:
            configured = await client.post("/config", json=payload, headers=headers)
            assert configured.status_code == 200, configured.text
            await wait_for(lambda: bool(mock_core.telemetry_requests and mock_core.event_requests))

            entities = assert_entities_response(
                (await client.get("/entities", headers=headers)).json()
            )["entities"]
            ap_entity = next(
                entity for entity in entities if entity["entity_type"] == "access_point"
            )
            assert len([item for item in entities if item["entity_type"] == "display_tag"]) == 2

            telemetry_request = mock_core.assert_telemetry_sent(
                config_id="oepl-test", device_id=ap_entity["device_id"]
            )
            assert telemetry_request.json_body["metrics"]["ap_tag_count"] == 2
            assert telemetry_request.json_body["metrics"]["ap_pending_transfer_count"] == 2
            mock_core.assert_event_sent(config_id="oepl-test", event_type="runtime.config.applied")

            refreshed = await client.post(
                "/command",
                headers=headers,
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "refresh",
                    "device_id": ap_entity["device_id"],
                    "config_id": "oepl-test",
                    "params": {},
                    "capability": "device.refresh",
                },
            )
            assert refreshed.status_code == 200, refreshed.text
            assert refreshed.json()["status"] == "success"
            await wait_for(
                lambda: any(
                    request.json_body.get("type") == "tag.removed"
                    for request in mock_core.event_requests
                )
            )
            mock_core.assert_event_sent(config_id="oepl-test", event_type="tag.removed")
    finally:
        await asyncio.sleep(0.05)
        state.telemetry.core_base_url = original_telemetry_url
        state.events.core_base_url = original_event_url
        mock_core.shutdown()
