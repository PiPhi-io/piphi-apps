from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from piphi_network_thinqconnect.lib.push import (
    DEVICE_PUSH_MESSAGE,
    DEVICE_STATUS_MESSAGE,
    ExpiringMessageSet,
    ThinQPushSupervisor,
    parse_push_message,
)


class FakeTransport:
    def __init__(self) -> None:
        self.device_ids: set[str] = set()
        self.on_message = None
        self.on_disconnect = None
        self.started = asyncio.Event()
        self.closed = 0
        self.renewals: list[set[str]] = []

    async def start(self, *, device_ids, on_message, on_disconnect) -> None:
        self.device_ids = set(device_ids)
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.started.set()

    async def renew(self, *, device_ids) -> None:
        self.renewals.append(set(device_ids))

    async def close(self) -> None:
        self.closed += 1


async def wait_until(predicate, *, attempts: int = 100) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


def test_push_message_parsing_prefers_provider_identity_and_bounds_input() -> None:
    envelope = parse_push_message(
        json.dumps(
            {
                "messageId": "message-1",
                "data": {"deviceId": "fridge-1", "state": {"doorState": "OPEN"}},
            }
        )
    )

    assert envelope.device_id == "fridge-1"
    assert envelope.message_id == "message-1"
    assert envelope.push_type is None
    assert envelope.status_report is None
    assert envelope.push_code is None
    assert envelope.payload["data"]["state"]["doorState"] == "OPEN"
    with pytest.raises(TypeError, match="JSON object"):
        parse_push_message("[]")
    with pytest.raises(ValueError, match="maximum supported size"):
        parse_push_message(b"x" * 1_048_577)


def test_push_message_parses_home_assistant_verified_message_shapes() -> None:
    status = parse_push_message(
        json.dumps(
            {
                "deviceId": "fridge-1",
                "deviceType": "REFRIGERATOR",
                "pushType": DEVICE_STATUS_MESSAGE,
                "report": {"doorStatus": {"doorState": "OPEN"}},
            }
        )
    )
    notification = parse_push_message(
        json.dumps(
            {
                "deviceId": "fridge-1",
                "deviceType": "REFRIGERATOR",
                "pushType": DEVICE_PUSH_MESSAGE,
                "pushCode": "DOOR_OPEN_WARNING",
            }
        )
    )

    assert status.status_report == {"doorStatus": {"doorState": "OPEN"}}
    assert status.push_code is None
    assert notification.status_report is None
    assert notification.push_code == "DOOR_OPEN_WARNING"


def test_push_message_hash_and_deduplication_are_bounded() -> None:
    first = parse_push_message('{"deviceId":"fridge-1","state":{"door":"OPEN"}}')
    second = parse_push_message('{"state":{"door":"OPEN"},"deviceId":"fridge-1"}')
    assert first.message_id == second.message_id

    seen = ExpiringMessageSet(ttl_seconds=5, maximum=2)
    assert seen.add(first.message_id, now=1) is True
    assert seen.add(first.message_id, now=2) is False
    assert seen.add("second", now=3) is True
    assert seen.add("third", now=4) is True
    assert seen.add(first.message_id, now=4) is True
    assert seen.add("second", now=10) is True


def test_supervisor_reconciles_before_streaming_and_emits_confirmed_transition() -> (
    None
):
    async def scenario() -> None:
        transports: list[FakeTransport] = []
        refreshes: list[str] = []
        events: list[tuple[str, str, dict[str, Any], str]] = []
        states = [
            {"metrics": {"door_open": False}},
            {"metrics": {"door_open": True}},
        ]

        async def factory(_account):
            transport = FakeTransport()
            transports.append(transport)
            return transport

        async def refresh(entry_id: str):
            refreshes.append(entry_id)
            return states.pop(0) if states else {"metrics": {"door_open": True}}

        supervisor = ThinQPushSupervisor(
            transport_factory=factory,
            refresh=refresh,
            emit_event=lambda *args: events.append(args),
            retry_floor_seconds=0,
        )
        await supervisor.add_device(
            {
                "id": "cfg-fridge",
                "device_id": "fridge-1",
                "device_type": "DEVICE_REFRIGERATOR",
                "access_token": "secret",
                "country_code": "US",
                "client_id": "client-1",
            }
        )
        await wait_until(lambda: bool(transports) and transports[0].started.is_set())
        assert refreshes == ["cfg-fridge"]
        assert not any(event[1].startswith("refrigerator.door") for event in events)

        message = b'{"messageId":"event-1","deviceId":"fridge-1"}'
        transports[0].on_message(message)
        await wait_until(
            lambda: any(event[1] == "refrigerator.door.opened" for event in events)
        )
        assert refreshes == ["cfg-fridge", "cfg-fridge"]
        transports[0].on_message(message)
        await asyncio.sleep(0)
        assert refreshes == ["cfg-fridge", "cfg-fridge"]
        assert (
            "cfg-fridge",
            "refrigerator.door.opened",
            {"door_open": True, "source": "lg_thinq_push"},
            "warning",
        ) in events
        await supervisor.shutdown()

    asyncio.run(scenario())


def test_supervisor_shares_account_transport_and_reconciles_after_disconnect() -> None:
    async def scenario() -> None:
        transports: list[FakeTransport] = []
        refreshes: list[str] = []
        events: list[tuple[str, str, dict[str, Any], str]] = []

        async def factory(_account):
            transport = FakeTransport()
            transports.append(transport)
            return transport

        async def refresh(entry_id: str):
            refreshes.append(entry_id)
            return {"metrics": {"door_open": False}}

        supervisor = ThinQPushSupervisor(
            transport_factory=factory,
            refresh=refresh,
            emit_event=lambda *args: events.append(args),
            retry_floor_seconds=0,
        )
        common = {
            "access_token": "secret",
            "country_code": "US",
            "client_id": "client-1",
        }
        await supervisor.add_device(
            {
                **common,
                "id": "cfg-1",
                "device_id": "fridge-1",
                "device_type": "DEVICE_REFRIGERATOR",
            }
        )
        await supervisor.add_device(
            {
                **common,
                "id": "cfg-2",
                "device_id": "washer-1",
                "device_type": "DEVICE_WASHER",
            }
        )
        await wait_until(lambda: bool(transports) and transports[0].started.is_set())
        assert transports[0].device_ids == {"fridge-1", "washer-1"}
        assert refreshes == ["cfg-1", "cfg-2"]

        transports[0].on_disconnect()
        await wait_until(
            lambda: len(transports) == 2 and transports[1].started.is_set()
        )
        assert refreshes == ["cfg-1", "cfg-2", "cfg-1", "cfg-2"]
        assert {
            event[0] for event in events if event[1] == "thinq.push.reconciled"
        } == {
            "cfg-1",
            "cfg-2",
        }
        assert any(event[1] == "thinq.push.disconnected" for event in events)
        await supervisor.shutdown()

    asyncio.run(scenario())


def test_supervisor_emits_sanitized_push_notification_after_snapshot_refresh() -> None:
    async def scenario() -> None:
        transport = FakeTransport()
        events: list[tuple[str, str, dict[str, Any], str]] = []

        async def refresh(_entry_id: str):
            return {"metrics": {"door_open": False}}

        supervisor = ThinQPushSupervisor(
            transport_factory=lambda _account: asyncio.sleep(0, result=transport),
            refresh=refresh,
            emit_event=lambda *args: events.append(args),
            retry_floor_seconds=0,
        )
        await supervisor.add_device(
            {
                "id": "cfg-fridge",
                "device_id": "fridge-1",
                "device_type": "DEVICE_REFRIGERATOR",
                "access_token": "secret",
                "country_code": "US",
                "client_id": "client-1",
            }
        )
        await wait_until(lambda: transport.started.is_set())
        transport.on_message(
            b'{"deviceId":"fridge-1","pushType":"DEVICE_PUSH",'
            b'"pushCode":"DOOR_OPEN_WARNING"}'
        )
        await wait_until(
            lambda: any(event[1] == "refrigerator.notification" for event in events)
        )

        assert (
            "cfg-fridge",
            "refrigerator.notification",
            {"code": "DOOR_OPEN_WARNING", "source": "lg_thinq_push"},
            "info",
        ) in events
        assert "secret" not in json.dumps(events)
        await supervisor.shutdown()

    asyncio.run(scenario())
