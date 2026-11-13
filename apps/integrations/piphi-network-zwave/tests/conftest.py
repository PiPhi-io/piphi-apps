from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    "/tmp/opencode/piphi-network-zwave-tests.sqlite3",
)

from piphi_network_zwave import state


class FakeSidecarClient:
    commands: list[dict[str, Any]] = []
    snapshot_calls = 0

    @classmethod
    def reset(cls) -> None:
        cls.commands = []
        cls.snapshot_calls = 0

    async def snapshot(self) -> dict[str, Any]:
        type(self).snapshot_calls += 1
        switch_value = next(
            (
                call["params"]["value"]
                for call in reversed(type(self).commands)
                if call["command"] == "set_value"
            ),
            False,
        )
        return {
            "schema_version": "piphi.zwave.snapshot.v1",
            "generated_at": "2026-11-13T20:00:00Z",
            "config_id": "sidecar-controller",
            "stream_id": "stream-test-1",
            "latest_sequence": 4,
            "dropped_event_count": 0,
            "controller": {"lifecycle": "ready", "driverReady": True},
            "nodes": [
                {
                    "node_id": 2,
                    "name": "Kitchen plug",
                    "status": "alive",
                    "ready": True,
                    "manufacturer_id": 900,
                    "values": [
                        {
                            "id": {
                                "command_class": 37,
                                "endpoint": 0,
                                "property": "currentValue",
                            },
                            "label": "Current value",
                            "value": False,
                            "metadata": {
                                "type": "boolean",
                                "readable": True,
                                "writeable": False,
                                "stateful": True,
                            },
                        },
                        {
                            "id": {
                                "command_class": 37,
                                "endpoint": 0,
                                "property": "targetValue",
                            },
                            "label": "Target value",
                            "value": switch_value,
                            "metadata": {
                                "type": "boolean",
                                "readable": True,
                                "writeable": True,
                                "stateful": True,
                            },
                        },
                        {
                            "id": {
                                "command_class": 50,
                                "endpoint": 0,
                                "property": "value",
                                "property_key": 65537,
                            },
                            "label": "Power",
                            "value": 46.7,
                            "metadata": {
                                "type": "number",
                                "readable": True,
                                "writeable": False,
                                "stateful": True,
                                "unit": "W",
                            },
                        },
                    ],
                },
                {
                    "node_id": 5,
                    "name": "Hall sensor",
                    "status": "asleep",
                    "ready": True,
                    "values": [
                        {
                            "id": {
                                "command_class": 49,
                                "endpoint": 0,
                                "property": "Air temperature",
                                "property_key": 1,
                            },
                            "property_name": "Air temperature",
                            "label": "Air temperature",
                            "value": 22.1,
                            "metadata": {
                                "type": "number",
                                "readable": True,
                                "writeable": False,
                                "stateful": True,
                                "unit": "°C",
                            },
                        },
                        {
                            "id": {
                                "command_class": 128,
                                "endpoint": 0,
                                "property": "level",
                            },
                            "label": "Battery level",
                            "value": 87,
                            "metadata": {
                                "type": "number",
                                "readable": True,
                                "writeable": False,
                                "stateful": True,
                                "unit": "%",
                                "min": 0,
                                "max": 100,
                            },
                        },
                    ],
                },
            ],
        }

    async def events(self, *, after: int, limit: int = 500) -> dict[str, Any]:
        return {
            "events": [],
            "next_cursor": after,
            "first_sequence": 1,
            "latest_sequence": 4,
            "stream_id": "stream-test-1",
            "gap": False,
            "dropped": 0,
        }

    async def command(
        self,
        *,
        config_id: str,
        command: str,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        call = {
            "config_id": config_id,
            "command": command,
            "params": params or {},
            "idempotency_key": idempotency_key,
        }
        type(self).commands.append(call)
        return {"ok": True, **call}


@pytest.fixture(autouse=True)
def fake_sidecar(monkeypatch: pytest.MonkeyPatch):
    FakeSidecarClient.reset()
    monkeypatch.setattr(state, "client_factory", FakeSidecarClient)
    yield FakeSidecarClient
