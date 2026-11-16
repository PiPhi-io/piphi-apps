from __future__ import annotations

import json

import httpx
import pytest

from piphi_network_android_tv.adb_sidecar_client import (
    MAX_SIDECAR_RESPONSE_BYTES,
    AdbSidecarClient,
    AdbSidecarConfigurationError,
    AdbSidecarError,
    AdbSidecarProtocolError,
)
from piphi_network_android_tv.schemas import DeviceConfig


def adb_config() -> DeviceConfig:
    return DeviceConfig(
        id="living-room-adb",
        host="192.0.2.20",
        alias="Living Room",
        transport="adb",
    )


def snapshot_payload() -> dict[str, object]:
    return {
        "schema_version": "piphi.adb.snapshot.v1",
        "connected": True,
        "authorized": True,
        "lifecycle": "ready",
        "service_available": True,
        "target_id": "adb-opaque-lease",
        "device_manufacturer": "Example",
        "device_model": "TV",
        "android_release": "14",
        "android_sdk": "34",
        "queue_depth": 0,
        "queue_capacity": 16,
        "queue_high_water_mark": 1,
        "reconnect_count": 1,
        "request_success_count": 2,
        "request_failure_count": 0,
        "timeout_count": 0,
        "transport_error_count": 0,
        "operation_duration_ms": 1.5,
        "last_error_code": None,
        "config_id": "living-room-adb",
    }


@pytest.mark.anyio
async def test_configure_refresh_key_and_remove_use_only_opaque_target() -> None:
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        assert request.headers["authorization"] == "Bearer internal-token"
        if request.url.path == "/config":
            body = json.loads(request.content)
            assert body == {
                "id": "living-room-adb",
                "host": "192.0.2.20",
                "port": 5555,
                "alias": "Living Room",
                "queue_capacity": 16,
                "connect_timeout_ms": 5000,
                "operation_timeout_ms": 5000,
            }
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/adb/snapshot":
            assert dict(request.url.params) == {"config_id": "living-room-adb"}
            return httpx.Response(200, json=snapshot_payload())
        if request.url.path == "/v1/adb/execute":
            body = json.loads(request.content)
            assert body["target"] == {"target_id": "adb-opaque-lease"}
            assert "host" not in body and "serial" not in body and "shell" not in str(body)
            if body["command"]["operation"] == "property_query":
                return httpx.Response(
                    200,
                    json={
                        "version": "1",
                        "request_id": body["request_id"],
                        "status": "completed",
                        "result": {
                            "operation": "property_query",
                            "properties": {
                                "ro.product.manufacturer": "Example",
                                "ro.product.model": "TV",
                                "ro.build.version.release": "14",
                                "ro.build.version.sdk": "34",
                            },
                        },
                    },
                )
            assert body["command"] == {
                "operation": "key_event",
                "key": "enter",
                "repeat": 1,
            }
            return httpx.Response(
                200,
                json={
                    "version": "1",
                    "request_id": body["request_id"],
                    "status": "completed",
                    "result": {"operation": "key_event", "repeats_completed": 1},
                },
            )
        if request.url.path == "/deconfigure":
            assert json.loads(request.content) == {"config_id": "living-room-adb"}
            return httpx.Response(200, json={"removed": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    http = httpx.AsyncClient(
        base_url="http://sidecar",
        transport=httpx.MockTransport(handler),
    )
    client = AdbSidecarClient(token="internal-token", client=http)

    configured = await client.configure(adb_config())
    refreshed = await client.refresh("living-room-adb", timeout_ms=2_000)
    await client.send_key("living-room-adb", "DPAD_CENTER", timeout_ms=2_000)
    assert await client.remove("living-room-adb") is True

    assert configured.connected is True
    assert refreshed.android_release == "14"
    assert [request.url.path for request in observed].count("/v1/adb/execute") == 2
    await http.aclose()


@pytest.mark.anyio
async def test_unsupported_adb_key_fails_before_transport() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if request.url.path == "/config":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json=snapshot_payload())

    http = httpx.AsyncClient(base_url="http://sidecar", transport=httpx.MockTransport(handler))
    client = AdbSidecarClient(token="internal-token", client=http)
    await client.configure(adb_config())
    before = requests

    with pytest.raises(ValueError, match="not supported by ADB"):
        await client.send_key("living-room-adb", "POWER", timeout_ms=1_000)
    assert requests == before
    await http.aclose()


@pytest.mark.anyio
async def test_uncertain_key_error_is_sanitized_and_never_retried() -> None:
    key_attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal key_attempts
        if request.url.path == "/config":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/adb/snapshot":
            return httpx.Response(200, json=snapshot_payload())
        key_attempts += 1
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "version": "1",
                "request_id": body["request_id"],
                "status": "error",
                "error": "offline",
                "message": "secret endpoint detail; key outcome unknown",
                "retry_after_ms": None,
            },
        )

    http = httpx.AsyncClient(base_url="http://sidecar", transport=httpx.MockTransport(handler))
    client = AdbSidecarClient(token="internal-token", client=http)
    await client.configure(adb_config())

    with pytest.raises(AdbSidecarError, match="ADB target is offline") as exc:
        await client.send_key("living-room-adb", "HOME", timeout_ms=1_000)
    assert exc.value.code == "offline"
    assert "secret" not in str(exc.value)
    assert key_attempts == 1
    await http.aclose()


@pytest.mark.anyio
async def test_key_reacquires_changed_lease_before_single_execute() -> None:
    snapshots = 0
    execute_targets: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal snapshots
        if request.url.path == "/config":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/adb/snapshot":
            snapshots += 1
            payload = snapshot_payload()
            payload["target_id"] = "lease-before" if snapshots == 1 else "lease-after"
            return httpx.Response(200, json=payload)
        body = json.loads(request.content)
        execute_targets.append(body["target"]["target_id"])
        return httpx.Response(
            200,
            json={
                "version": "1",
                "request_id": body["request_id"],
                "status": "completed",
                "result": {"operation": "key_event", "repeats_completed": 1},
            },
        )

    http = httpx.AsyncClient(base_url="http://sidecar", transport=httpx.MockTransport(handler))
    client = AdbSidecarClient(token="internal-token", client=http)
    await client.configure(adb_config())

    await client.send_key("living-room-adb", "HOME", timeout_ms=1_000)

    assert execute_targets == ["lease-after"]
    await http.aclose()


@pytest.mark.anyio
async def test_client_fails_closed_for_missing_auth_and_unknown_lease() -> None:
    client = AdbSidecarClient(
        token="",
        client=httpx.AsyncClient(
            base_url="http://sidecar",
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        ),
    )
    with pytest.raises(AdbSidecarConfigurationError, match="authentication"):
        await client.configure(adb_config())

    authenticated = AdbSidecarClient(
        token="token",
        client=httpx.AsyncClient(
            base_url="http://sidecar",
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        ),
    )
    with pytest.raises(AdbSidecarConfigurationError, match="not configured"):
        await authenticated.snapshot("missing")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content",
    [
        b"x" * (MAX_SIDECAR_RESPONSE_BYTES + 1),
        b'{"schema_version":"piphi.adb.snapshot.v1","schema_version":"duplicate"}',
    ],
)
async def test_sidecar_responses_are_byte_bounded_and_duplicate_free(content: bytes) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/config":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/deconfigure":
            return httpx.Response(200, json={"removed": True})
        return httpx.Response(200, content=content)

    http = httpx.AsyncClient(base_url="http://sidecar", transport=httpx.MockTransport(handler))
    client = AdbSidecarClient(token="token", client=http)
    with pytest.raises((AdbSidecarProtocolError, json.JSONDecodeError)):
        await client.configure(adb_config())
    await http.aclose()
