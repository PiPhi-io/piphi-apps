from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from piphi_android_adb_sidecar import state
from piphi_android_adb_sidecar.main import app
from piphi_android_adb_sidecar.parent_contract_v1 import ReadableProperty
from piphi_android_adb_sidecar.transport import (
    AdbCommandTimeoutError,
    AdbOfflineError,
    AdbOutcomeUnknownError,
    AdbQueueFullError,
    AdbUnauthorizedError,
    BoundedQueue,
)


class FakeSession:
    def __init__(self, config) -> None:
        self.config = config
        self.queue = BoundedQueue(config.queue_capacity)
        self.connected = False
        self.authorized = False
        self.target_id: str | None = None
        self.metadata: dict[str, str] = {}
        self.closed = False
        self.keys: list[str] = []

    async def open(self) -> None:
        self.connected = True
        self.authorized = True
        self.target_id = self.target_id or "adb-opaque-target"
        self.metadata = {"ro.product.model": "Fake TV"}

    async def close(self) -> None:
        self.connected = False
        self.authorized = False
        self.closed = True

    async def query_properties(
        self,
        properties: list[ReadableProperty],
        *,
        timeout_ms: int,
    ) -> dict[str, str]:
        assert timeout_ms == 2_000
        return {item.value: f"value-{item.value}" for item in properties}

    async def send_key(self, key, repeat: int, *, timeout_ms: int) -> int:
        assert timeout_ms == 2_000
        self.keys.extend([key.value] * repeat)
        return repeat


def config_payload(config_id: str = "adb-api") -> dict[str, Any]:
    return {
        "id": config_id,
        "host": "192.0.2.20",
        "port": 5555,
        "alias": "Living room TV",
    }


def request_payload(command: dict[str, Any], target_id: str = "adb-opaque-target") -> bytes:
    return json.dumps(
        {
            "version": "1",
            "request_id": "request-1",
            "target": {"target_id": target_id},
            "timeout_ms": 2_000,
            "command": command,
        }
    ).encode()


@pytest.mark.anyio
async def test_authenticated_private_api_executes_bounded_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "session_factory", FakeSession)
    monkeypatch.setenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN", "internal")
    headers = {"Authorization": "Bearer internal"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        try:
            configured = await client.post("/config", json=config_payload(), headers=headers)
            assert configured.status_code == 200
            second_target = await client.post(
                "/config",
                json=config_payload("adb-second-target")
                | {"host": "192.0.2.21"},
                headers=headers,
            )
            assert second_target.status_code == 503
            assert "adb-second-target" not in state.controllers
            assert (await client.get("/v1/adb/snapshot?config_id=adb-api")).status_code == 401

            snapshot = (
                await client.get(
                    "/v1/adb/snapshot?config_id=adb-api",
                    headers=headers,
                )
            ).json()
            assert snapshot["connected"] is True
            assert snapshot["authorized"] is True
            assert snapshot["target_id"] == "adb-opaque-target"
            assert "192.0.2.20" not in str(snapshot)

            properties = await client.post(
                "/v1/adb/execute",
                content=request_payload(
                    {
                        "operation": "property_query",
                        "properties": ["ro.product.model", "ro.build.version.sdk"],
                    }
                ),
                headers={**headers, "Content-Type": "application/json"},
            )
            assert properties.status_code == 200
            assert properties.json() == {
                "version": "1",
                "request_id": "request-1",
                "status": "completed",
                "result": {
                    "operation": "property_query",
                    "properties": {
                        "ro.product.model": "value-ro.product.model",
                        "ro.build.version.sdk": "value-ro.build.version.sdk",
                    },
                },
            }

            key = await client.post(
                "/v1/adb/execute",
                content=request_payload(
                    {"operation": "key_event", "key": "home", "repeat": 2}
                ),
                headers={**headers, "Content-Type": "application/json"},
            )
            assert key.json()["result"] == {
                "operation": "key_event",
                "repeats_completed": 2,
            }
            assert state.get_controller("adb-api").session.keys == ["home", "home"]

            unknown = await client.post(
                "/v1/adb/execute",
                content=request_payload(
                    {"operation": "key_event", "key": "home"},
                    target_id="adb-stale-target",
                ),
                headers={**headers, "Content-Type": "application/json"},
            )
            assert unknown.json()["error"] == "unsupported"
        finally:
            await client.post("/deconfigure/adb-api", headers=headers)


@pytest.mark.anyio
async def test_private_api_rejects_duplicate_fields_and_oversized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN", "internal")
    headers = {"Authorization": "Bearer internal", "Content-Type": "application/json"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        duplicate = await client.post(
            "/v1/adb/execute",
            content=b'{"version":"1","version":"1"}',
            headers=headers,
        )
        oversized = await client.post(
            "/v1/adb/execute",
            content=b" " * 4_097,
            headers=headers,
        )
    assert duplicate.status_code == 400
    assert oversized.status_code == 413


@pytest.mark.anyio
async def test_parent_api_always_fails_closed_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/state")).status_code == 503


@pytest.mark.anyio
async def test_private_api_maps_sanitized_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "session_factory", FakeSession)
    monkeypatch.setenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN", "internal")
    headers = {"Authorization": "Bearer internal", "Content-Type": "application/json"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        try:
            assert (
                await client.post("/config", json=config_payload("adb-errors"), headers=headers)
            ).status_code == 200
            controller = state.get_controller("adb-errors")

            async def fail_properties(properties, *, timeout_ms):
                del properties, timeout_ms
                raise AdbUnauthorizedError("secret device detail")

            controller.session.query_properties = fail_properties
            unauthorized = await client.post(
                "/v1/adb/execute",
                content=request_payload(
                    {"operation": "property_query", "properties": ["ro.product.model"]}
                ),
                headers=headers,
            )
            assert unauthorized.json()["error"] == "unauthorized"
            assert "secret" not in str(unauthorized.json())

            async def full_properties(properties, *, timeout_ms):
                del properties, timeout_ms
                raise AdbQueueFullError("internal queue detail")

            controller.session.query_properties = full_properties
            queue_full = await client.post(
                "/v1/adb/execute",
                content=request_payload(
                    {"operation": "property_query", "properties": ["ro.product.model"]}
                ),
                headers=headers,
            )
            assert queue_full.json()["error"] == "queue_full"
            assert queue_full.json()["retry_after_ms"] == 250

            async def timeout_properties(properties, *, timeout_ms):
                del properties, timeout_ms
                raise AdbCommandTimeoutError("internal timeout detail")

            controller.session.query_properties = timeout_properties
            timed_out = await client.post(
                "/v1/adb/execute",
                content=request_payload(
                    {"operation": "property_query", "properties": ["ro.product.model"]}
                ),
                headers=headers,
            )
            assert timed_out.json()["error"] == "timeout"

            async def unknown_key(key, repeat, *, timeout_ms):
                del key, repeat, timeout_ms
                raise AdbOutcomeUnknownError("internal key detail")

            controller.session.send_key = unknown_key
            uncertain = await client.post(
                "/v1/adb/execute",
                content=request_payload({"operation": "key_event", "key": "home"}),
                headers=headers,
            )
            assert uncertain.json()["error"] == "offline"
            assert "outcome is unknown" in uncertain.json()["message"]

            async def offline_properties(properties, *, timeout_ms):
                del properties, timeout_ms
                raise AdbOfflineError("internal endpoint detail")

            controller.session.query_properties = offline_properties
            offline = await client.post(
                "/v1/adb/execute",
                content=request_payload(
                    {"operation": "property_query", "properties": ["ro.product.model"]}
                ),
                headers=headers,
            )
            assert offline.json()["error"] == "offline"

            reconnect = await client.post(
                "/v1/adb/reconnect?config_id=adb-errors",
                headers=headers,
            )
            assert reconnect.status_code == 200
            assert reconnect.json()["reconnect_count"] >= 1

            rejected_body = await client.post(
                "/v1/adb/reconnect?config_id=adb-errors",
                json={"unexpected": True},
                headers=headers,
            )
            assert rejected_body.status_code == 400
        finally:
            await client.post("/deconfigure/adb-errors", headers=headers)
