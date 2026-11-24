from __future__ import annotations

import asyncio
import socket

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from piphi_network_tp_link.app import app
from piphi_network_tp_link.contract.config.routes import run_command_for_device
from piphi_network_tp_link.lib.schemas import TPLinkDeviceConfig
from piphi_network_tp_link.lib.security import redact, resolve_local_host
from piphi_network_tp_link.lib.store import registry
from piphi_network_tp_link.contract.config import routes as config_routes


def test_only_health_is_public_and_auth_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/entities").status_code == 503

    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "expected")
    with TestClient(app) as client:
        assert client.get(
            "/entities", headers={"X-PiPhi-Integration-Token": "wrong"}
        ).status_code == 401


def test_credentials_are_secret_types_and_recursive_redaction_is_total() -> None:
    config = TPLinkDeviceConfig(
        id="plug-1", host="192.168.1.20", username="person@example.com", password="s3cret"
    )
    assert isinstance(config.username, SecretStr)
    assert isinstance(config.password, SecretStr)
    assert "s3cret" not in repr(config)
    value = redact(
        {"nested": [{"password": "s3cret", "token": "abc"}], "secret": SecretStr("hidden")}
    )
    assert value == {
        "nested": [{"password": "[redacted]", "token": "[redacted]"}],
        "secret": "[redacted]",
    }


def test_host_policy_rejects_public_mixed_and_rebinding_candidates(monkeypatch) -> None:
    def public(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", public)
    with pytest.raises(ValueError, match="private or link-local"):
        resolve_local_host("device.example")

    def mixed(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    with pytest.raises(ValueError, match="private or link-local"):
        resolve_local_host("rebinding.example")


def test_consequential_command_requires_external_certification(monkeypatch) -> None:
    registry.entries.clear()
    registry.set(
        "plug-1",
        {
            "device_id": "plug-1",
            "host": "192.168.1.20",
            "controls_enabled": True,
            "certified_profile": "missing-profile",
            "allowed_commands": ["turn_on"],
            "observed_model": "KP115",
        },
    )
    monkeypatch.delenv("PIPHI_TP_LINK_CERTIFIED_PROFILES", raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_command_for_device(device_id="plug-1", command="turn_on"))
    assert exc.value.status_code == 403


def test_power_transition_is_deduplicated_and_has_no_startup_event(monkeypatch) -> None:
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.set("plug-1", {"config_id": "plug-1", "device_id": "plug-1"})
    states = iter([{"is_on": False}, {"is_on": False}, {"is_on": True}, {"is_on": True}])
    events: list[str] = []

    async def fake_fetch(**kwargs):
        return next(states)

    monkeypatch.setattr(config_routes, "fetch_device_state", fake_fetch)
    monkeypatch.setattr(config_routes, "schedule_telemetry_delivery", lambda **kwargs: None)
    monkeypatch.setattr(
        config_routes,
        "schedule_event_send",
        lambda **kwargs: events.append(kwargs["event_type"]),
    )
    for _ in range(4):
        asyncio.run(
            config_routes.fetch_and_store_state(
                host="192.168.1.20", device_id="plug-1", container_id="runtime-1"
            )
        )
    assert events == ["device.turned_on"]


def test_polling_marks_stale_once_then_emits_one_recovery(monkeypatch) -> None:
    registry.entries.clear()
    registry.set("plug-1", {"config_id": "plug-1", "device_id": "plug-1"})
    attempts = 0
    events: list[str] = []

    async def flaky_fetch(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            raise TimeoutError("offline")
        return {"is_on": False}

    async def bounded_sleep(_seconds):
        if attempts >= 4:
            raise asyncio.CancelledError

    monkeypatch.setattr(config_routes, "fetch_and_store_state", flaky_fetch)
    monkeypatch.setattr(config_routes.asyncio, "sleep", bounded_sleep)
    monkeypatch.setattr(
        config_routes,
        "schedule_event_send",
        lambda **kwargs: events.append(kwargs["event_type"]),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            config_routes.poll_device_state(
                host="192.168.1.20", device_id="plug-1", container_id=None
            )
        )
    assert events == ["device.stale", "device.recovered"]
