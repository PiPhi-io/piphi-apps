from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from piphi_camera_stream.main import app
from piphi_camera_stream.schemas import DeviceConfig
from piphi_camera_stream.source_probe import SourceProbeResult
from piphi_camera_stream.state import (
    apply_config,
    refresh_all_entries,
    refresh_entry,
    registry,
    remove_config,
)


@pytest.fixture(autouse=True)
def clear_runtime_state() -> None:
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()


@pytest.mark.anyio
async def test_config_rejects_an_unreachable_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "piphi_camera_stream.state.probe_camera_source",
        AsyncMock(return_value=SourceProbeResult(False, "source_unreachable")),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/config",
            json={"id": "front-door", "source_url": "rtsp://camera.local/live"},
        )

    assert response.status_code == 502
    assert registry.get("front-door") is None


@pytest.mark.anyio
async def test_availability_tracks_probe_failure_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="piphi_camera_stream.state")
    probe = AsyncMock(
        side_effect=[
            SourceProbeResult(True, "available"),
            SourceProbeResult(False, "timeout"),
            SourceProbeResult(False, "timeout"),
            SourceProbeResult(True, "available"),
        ]
    )
    monkeypatch.setattr("piphi_camera_stream.state.probe_camera_source", probe)
    await apply_config(
        DeviceConfig(id="front-door", source_url="rtsp://camera.local/live")
    )
    entry = registry.get("front-door")

    await refresh_entry(entry)
    await refresh_entry(entry)
    await refresh_entry(entry)

    state = registry.state_snapshots["front-door"]["state"]
    assert state["connected"] is True
    assert state["availability_reason"] == "available"
    assert (
        caplog.messages.count("camera source became unavailable config_id=front-door")
        == 1
    )
    assert caplog.messages.count("camera source recovered config_id=front-door") == 1


@pytest.mark.anyio
async def test_deconfigure_clears_state_and_empty_entities_have_no_phantom_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "piphi_camera_stream.state.probe_camera_source",
        AsyncMock(return_value=SourceProbeResult(True, "available")),
    )
    await apply_config(
        DeviceConfig(id="front-door", source_url="rtsp://camera.local/live")
    )

    assert await remove_config("front-door") is True
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/entities")

    assert registry.state_snapshots == {}
    assert response.json()["entities"] == []


@pytest.mark.anyio
async def test_refresh_all_entries_uses_bounded_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available = SourceProbeResult(True, "available")
    monkeypatch.setattr(
        "piphi_camera_stream.state.probe_camera_source",
        AsyncMock(return_value=available),
    )
    for index in range(6):
        await apply_config(
            DeviceConfig(
                id=f"camera-{index}", source_url=f"rtsp://camera-{index}.local/live"
            )
        )

    active = 0
    maximum = 0
    counter_lock = asyncio.Lock()

    async def bounded_probe(*_args, **_kwargs) -> SourceProbeResult:
        nonlocal active, maximum
        async with counter_lock:
            active += 1
            maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        async with counter_lock:
            active -= 1
        return available

    monkeypatch.setenv("PIPHI_CAMERA_PROBE_CONCURRENCY", "2")
    monkeypatch.setattr("piphi_camera_stream.state.probe_camera_source", bounded_probe)

    results = await refresh_all_entries()

    assert len(results) == 6
    assert maximum == 2


@pytest.mark.anyio
async def test_diagnostics_hashes_active_config_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "piphi_camera_stream.state.probe_camera_source",
        AsyncMock(return_value=SourceProbeResult(True, "available")),
    )
    await apply_config(
        DeviceConfig(id="private-front-door", source_url="rtsp://camera.local/live")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/diagnostics")

    diagnostics = response.json()["diagnostics"]
    assert diagnostics["active_config_count"] == 1
    assert "active_config_ids" not in diagnostics
    assert diagnostics["active_config_fingerprints"] != ["private-front-door"]
    assert "private-front-door" not in response.text
