from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from piphi_runtime_testkit_python import (
    MockCoreServer,
    assert_entities_response,
    build_config_payload,
    build_runtime_headers,
)

from piphi_network_zwave import state as runtime_state
from piphi_network_zwave.main import app


SCENARIO = json.loads(
    (Path(__file__).parent / "fixtures" / "runtime-vertical-slice.json").read_text()
)
ENTITY_ID = f"zwave-{'b' * 64}-node-{'c' * 64}-endpoint-0"
CONFIG_ID = "vertical-slice-network"
CONTAINER_ID = "vertical-slice-container"
INTERNAL_TOKEN = "vertical-slice-fake-token"


class ScriptedSidecarBackend:
    """Small protocol adapter prototype with explicit event injection."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        self._scenario = copy.deepcopy(scenario)
        self._reported = False
        self._event_pending = False
        self.commands: list[dict[str, Any]] = []
        self.snapshot_calls = 0

    async def snapshot(self) -> dict[str, Any]:
        self.snapshot_calls += 1
        key = "reported_snapshot" if self._reported else "initial_snapshot"
        return copy.deepcopy(self._scenario[key])

    async def events(self, *, after: int, limit: int = 500) -> dict[str, Any]:
        del limit
        event = self._scenario["event"]
        if self._event_pending and after < event["sequence"]:
            self._event_pending = False
            return {
                "events": [copy.deepcopy(event)],
                "next_cursor": event["sequence"],
                "first_sequence": 1,
                "latest_sequence": event["sequence"],
                "stream_id": self._scenario["reported_snapshot"]["stream_id"],
                "gap": False,
                "dropped": 0,
            }
        snapshot = self._scenario[
            "reported_snapshot" if self._reported else "initial_snapshot"
        ]
        return {
            "events": [],
            "next_cursor": after,
            "first_sequence": 1,
            "latest_sequence": snapshot["latest_sequence"],
            "stream_id": snapshot["stream_id"],
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
            "params": copy.deepcopy(params or {}),
        }
        self.commands.append(call)
        return {"ok": True, **call, "idempotency_key": idempotency_key}

    def emit_reported_value(self) -> None:
        self._reported = True
        self._event_pending = True


async def wait_for(
    assertion: Callable[[], Awaitable[None]], *, timeout: float = 2.0
) -> None:
    async with asyncio.timeout(timeout):
        while True:
            try:
                await assertion()
            except AssertionError:
                await asyncio.sleep(0.01)
            else:
                return


@pytest.mark.anyio
async def test_authenticated_switch_meter_command_event_reload_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = ScriptedSidecarBackend(SCENARIO)
    mock_core = MockCoreServer()
    headers = build_runtime_headers(
        container_id=CONTAINER_ID,
        internal_token=INTERNAL_TOKEN,
    )
    previous_auth = (
        runtime_state.runtime.auth.container_id,
        runtime_state.runtime.auth.internal_token,
    )
    runtime_state.runtime.auth.update(
        container_id=CONTAINER_ID,
        internal_token=INTERNAL_TOKEN,
    )
    monkeypatch.setattr(runtime_state, "client_factory", lambda: backend)
    monkeypatch.setattr(
        runtime_state,
        "CONFIG_STORE_PATH",
        tmp_path / "controller-configs.json",
    )
    monkeypatch.setattr(
        runtime_state.starter.event_client,
        "core_base_url",
        mock_core.base_url,
    )

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=headers,
        ) as client:
            denied = await client.get("/entities", headers={"X-Container-Id": "wrong"})
            assert denied.status_code == 401

            configured = await client.post(
                "/config",
                json=build_config_payload(
                    config_id=CONFIG_ID,
                    device_id=CONFIG_ID,
                    container_id=CONTAINER_ID,
                    integration_id="piphi-network-zwave",
                    extra={
                        "alias": "Vertical slice network",
                        "event_poll_interval_seconds": 0.25,
                    },
                ),
            )
            assert configured.status_code == 200, configured.text

            entities_payload = assert_entities_response(
                (await client.get("/entities")).json()
            )
            entity = next(
                item
                for item in entities_payload["entities"]
                if item["device_id"] == ENTITY_ID
            )
            original_entity_id = entity["id"]
            assert entity["entity_type"] == "switch"
            assert {"switch_state", "power_w"} <= set(entity["capabilities"])
            assert "set_switch" in {
                command["id"] for command in entity["available_commands"]
            }

            initial_state = (await client.get("/state")).json()["entries"][CONFIG_ID]
            initial_node = initial_state["latest_state"]["nodes"][ENTITY_ID]
            assert initial_node["switch_state"] is False
            assert initial_node["power_w"] == 46.7

            commanded = await client.post(
                "/command",
                headers={
                    **headers,
                    "X-PiPhi-Idempotency-Key": f"vertical-slice-{uuid4()}",
                },
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "set_switch",
                    "target": {
                        "config_id": CONFIG_ID,
                        "device_id": ENTITY_ID,
                    },
                    "params": {"value": True},
                    "capability": "action.set_switch",
                },
            )
            assert commanded.status_code == 200, commanded.text
            assert commanded.json()["status"] == "success"
            assert backend.commands == [SCENARIO["expected_command"]]

            state_before_report = (await client.get("/state")).json()["entries"][
                CONFIG_ID
            ]
            assert (
                state_before_report["latest_state"]["nodes"][ENTITY_ID][
                    "switch_state"
                ]
                is False
            )

            backend.emit_reported_value()

            async def assert_reported_state_and_core_event() -> None:
                state = (await client.get("/state")).json()["entries"][CONFIG_ID][
                    "latest_state"
                ]
                assert state["nodes"][ENTITY_ID]["switch_state"] is True
                assert state["nodes"][ENTITY_ID]["power_w"] == 47.1
                event = mock_core.assert_event_sent(
                    device_id=ENTITY_ID,
                    config_id=CONFIG_ID,
                    event_type="node.value_updated",
                )
                assert event.json_body["data"]["payload"]["newValue"] is True
                assert "network_key" not in event.body.decode().lower()

            await wait_for(assert_reported_state_and_core_event)

            await runtime_state.shutdown_supervisors()
            runtime_state.registry.remove(CONFIG_ID)
            runtime_state.node_models.pop(CONFIG_ID, None)
            await runtime_state.restore_persisted_configs()

            reloaded_entities = assert_entities_response(
                (await client.get("/entities")).json()
            )["entities"]
            reloaded = next(
                item for item in reloaded_entities if item["device_id"] == ENTITY_ID
            )
            assert reloaded["id"] == original_entity_id
            assert backend.commands == [SCENARIO["expected_command"]]

            removed = await client.post(f"/deconfigure/{CONFIG_ID}")
            assert removed.status_code == 200
            assert removed.json()["removed"] is True
            assert runtime_state.registry.get(CONFIG_ID) is None
            assert CONFIG_ID not in runtime_state.supervisors
            assert CONFIG_ID not in runtime_state.node_models
    finally:
        if runtime_state.registry.get(CONFIG_ID) is not None:
            await runtime_state.remove_config(CONFIG_ID)
        await runtime_state.shutdown_supervisors()
        runtime_state.runtime.auth.container_id = previous_auth[0]
        runtime_state.runtime.auth.internal_token = previous_auth[1]
        mock_core.shutdown()
