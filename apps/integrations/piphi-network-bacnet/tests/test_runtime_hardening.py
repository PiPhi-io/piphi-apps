from __future__ import annotations

import httpx
import pytest

from piphi_network_bacnet.bacnet_client import BacnetReadError
from piphi_network_bacnet.main import app
from piphi_network_bacnet.schemas import DeviceConfig
from piphi_network_bacnet.state import (
    next_poll_delay,
    poll_once,
    registry,
    runtime_configs,
)


def config(**updates) -> DeviceConfig:
    values = {
        "id": "senseedge-hardening",
        "host": "192.0.2.20",
        "device_instance": 1234,
        "local_address": "192.0.2.10/24",
        "alias": "Original",
    }
    values.update(updates)
    return DeviceConfig.model_validate(values)


@pytest.mark.anyio
async def test_only_health_is_public_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/health")).status_code == 200
        for method, path in (
            ("GET", "/diagnostics"),
            ("POST", "/discover"),
            ("POST", "/config"),
            ("POST", "/config/sync"),
            ("POST", "/deconfigure"),
            ("POST", "/deconfigure/example"),
            ("GET", "/ui-config"),
            ("GET", "/entities"),
            ("GET", "/state"),
            ("GET", "/contract"),
            ("GET", "/events"),
            ("POST", "/telemetry/example"),
            ("POST", "/telemetry/device/example/example"),
            ("POST", "/command"),
        ):
            response = await client.request(method, path)
            assert response.status_code == 503, (method, path, response.text)


@pytest.mark.anyio
async def test_runtime_token_is_compared_before_route_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/entities")).status_code == 401
        assert (
            await client.get(
                "/entities", headers={"X-PiPhi-Integration-Token": "wrong"}
            )
        ).status_code == 401
        assert (
            await client.get(
                "/entities",
                headers={"X-PiPhi-Integration-Token": "runtime-secret"},
            )
        ).status_code == 200


@pytest.mark.anyio
async def test_failed_reconfigure_preserves_active_config_and_snapshot(
    fake_bacnet_reader,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        initial = await client.post("/config", json=config().model_dump(mode="json"))
        assert initial.status_code == 200
        before = dict(registry.state_snapshots["senseedge-hardening"])

        fake_bacnet_reader.error = BacnetReadError("candidate did not answer")
        replacement = await client.post(
            "/config",
            json=config(alias="Replacement").model_dump(mode="json"),
        )

    assert replacement.status_code == 422
    assert runtime_configs["senseedge-hardening"].alias == "Original"
    assert registry.get("senseedge-hardening")["alias"] == "Original"
    assert registry.state_snapshots["senseedge-hardening"] == before


@pytest.mark.anyio
async def test_failed_poll_retains_last_good_values_and_deduplicates_transitions(
    fake_bacnet_reader,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/config", json=config().model_dump(mode="json"))
        assert response.status_code == 200

    fake_bacnet_reader.error = BacnetReadError("device unavailable")
    assert await poll_once("senseedge-hardening") is False
    assert await poll_once("senseedge-hardening") is False
    stale = registry.state_snapshots["senseedge-hardening"]["state"]
    assert stale["connected"] is False
    assert stale["stale"] is True
    assert stale["metrics"]["pm2_5_ug_m3"] == 12.5
    assert [event["event_type"] for event in registry.recent_events].count(
        "runtime.device.unavailable"
    ) == 1

    fake_bacnet_reader.error = None
    assert await poll_once("senseedge-hardening") is True
    assert await poll_once("senseedge-hardening") is True
    current = registry.state_snapshots["senseedge-hardening"]["state"]
    assert current["connected"] is True
    assert current["stale"] is False
    assert [event["event_type"] for event in registry.recent_events].count(
        "runtime.device.recovered"
    ) == 1


def test_poll_backoff_is_exponential_jittered_and_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("piphi_network_bacnet.state.random.uniform", lambda low, high: high)
    assert next_poll_delay(30, 1) == 66.0
    assert next_poll_delay(30, 2) == 132.0
    assert next_poll_delay(60, 20) == 900.0


@pytest.mark.anyio
async def test_reconfigure_cannot_replace_active_client_interface(
    fake_bacnet_reader,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (
            await client.post("/config", json=config().model_dump(mode="json"))
        ).status_code == 200
        response = await client.post(
            "/config",
            json=config(
                host="192.0.3.20",
                local_address="192.0.3.10/24",
                alias="Unsafe replacement",
            ).model_dump(mode="json"),
        )

    assert response.status_code == 422
    assert runtime_configs["senseedge-hardening"].alias == "Original"
