from __future__ import annotations

import asyncio

import httpx
import pytest

from piphi_modbus_rtu_sidecar.main import app
from piphi_modbus_rtu_sidecar.transport import (
    BoundedQueue,
    EventBuffer,
    crc16,
    frame_with_crc,
    sanitize,
    validate_rtu_response,
)
from piphi_modbus_rtu_sidecar.schemas import DeviceConfig
from piphi_modbus_rtu_sidecar import state


def test_crc_and_response_validation() -> None:
    payload = bytes.fromhex("0103021234")
    frame = frame_with_crc(payload)
    assert crc16(frame) == 0
    assert validate_rtu_response(frame, unit_id=1, function=3) == bytes.fromhex("021234")


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (bytes.fromhex("01030212340000"), "crc"),
        (frame_with_crc(bytes.fromhex("0203021234")), "unit"),
        (frame_with_crc(bytes.fromhex("018302")), "exception_2"),
    ],
)
def test_malformed_or_exception_responses_fail_closed(frame: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_rtu_response(frame, unit_id=1, function=3)


@pytest.mark.anyio
async def test_queue_serializes_requests_and_rejects_saturation() -> None:
    queue = BoundedQueue(capacity=1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked() -> str:
        entered.set()
        await release.wait()
        return "done"

    task = asyncio.create_task(queue.submit(blocked))
    await entered.wait()
    with pytest.raises(RuntimeError, match="saturated"):
        await queue.submit(blocked)
    release.set()
    assert await task == "done"
    assert queue.pending == 0
    assert queue.high_water_mark == 1


def test_replay_reports_drops_and_cursor_gaps() -> None:
    events = EventBuffer(capacity=10)
    for index in range(12):
        events.append("register.changed", {"index": index})
    page = events.read(after=1)
    assert page.gap is True
    assert page.dropped == 2
    assert page.first_sequence == 3
    assert page.latest_sequence == 12
    assert page.next_cursor == 12


def test_diagnostics_redact_sensitive_and_binary_values() -> None:
    assert sanitize(
        {
            "serial_port": "/dev/serial/by-id/private",
            "token": "secret",
            "response": b"raw",
            "safe": 42,
        }
    ) == {
        "serial_port": "[redacted]",
        "token": "[redacted]",
        "response": "[binary:3]",
        "safe": 42,
    }


@pytest.mark.anyio
async def test_parent_api_fails_closed_without_production_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_MODBUS_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        response = await client.post("/command", json={"command": "refresh"})
    assert response.status_code == 503


@pytest.mark.anyio
async def test_parent_api_requires_valid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_ENV", raising=False)
    monkeypatch.setenv("PIPHI_MODBUS_SIDECAR_TOKEN", "expected")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        denied = await client.post("/command", json={"command": "refresh"})
        accepted = await client.post(
            "/command",
            json={"command": "refresh"},
            headers={"Authorization": "Bearer expected"},
        )
    assert denied.status_code == 401
    assert accepted.status_code != 401


@pytest.mark.anyio
async def test_all_operational_routes_require_sidecar_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_MODBUS_SIDECAR_TOKEN", "expected")
    routes = [
        ("GET", "/state"),
        ("GET", "/entities"),
        ("GET", "/events"),
        ("GET", "/diagnostics"),
        ("GET", "/contract"),
        ("GET", "/ui-config"),
        ("POST", "/events/example"),
        ("POST", "/telemetry/example"),
        ("POST", "/discover"),
    ]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        assert (await client.get("/health")).status_code == 200
        for method, path in routes:
            denied = await client.request(method, path, json={})
            accepted = await client.request(
                method,
                path,
                json={},
                headers={"Authorization": "Bearer expected"},
            )
            assert denied.status_code == 401, path
            assert accepted.status_code != 401, path


@pytest.mark.anyio
async def test_controller_reopens_serial_descriptor_after_transport_failure() -> None:
    class ReplacingSession:
        def __init__(self) -> None:
            self.queue = BoundedQueue(10)
            self.opens = 0
            self.reads = 0

        async def open(self) -> None:
            self.opens += 1

        async def close(self) -> None:
            return None

        async def read(self, _point):
            self.reads += 1
            if self.reads == 1:
                raise OSError("descriptor replaced")
            return [42]

    config = DeviceConfig.model_validate(
        {
            "id": "recovery-test",
            "serial_port": "/dev/serial/by-id/recovery-test",
            "registers": [
                {
                    "id": "value",
                    "name": "Value",
                    "unit_id": 1,
                    "address": 0,
                }
            ],
        }
    )
    session = ReplacingSession()
    controller = state.BusController(
        config=config,
        entry=state.make_entry(config),
        session=session,  # type: ignore[arg-type]
    )
    assert await controller.open() is True
    assert controller.values["value"]["value"] == 42
    assert controller.reconnect_count == 1
    assert session.opens == 2
