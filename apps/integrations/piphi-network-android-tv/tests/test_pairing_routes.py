from __future__ import annotations

import httpx
import pytest

from piphi_network_android_tv.main import app
from piphi_network_android_tv.mdns_discovery import UnverifiedRemoteV2Candidate
from piphi_network_android_tv.remote_v2_pairing import (
    PairingSession,
    PairingSessionNotFoundError,
)
from piphi_network_android_tv.routes import discovery as discovery_routes
from piphi_network_android_tv.routes import pairing as pairing_routes


@pytest.mark.anyio
async def test_pairing_route_returns_only_credential_free_metadata(monkeypatch) -> None:
    async def start_pairing(*, config_id: str, host: str):
        assert host == "tv.local"
        return PairingSession(
            session_id="opaque-session",
            config_id=config_id,
            device_name="Living Room",
            expires_at=123.0,
        )

    monkeypatch.setattr(pairing_routes.pairing_manager, "start_pairing", start_pairing)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "test-token"}) as client:
        response = await client.post(
            "/pairing/start",
            json={"config_id": "living-room", "host": "tv.local"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "opaque-session",
        "config_id": "living-room",
        "device_name": "Living Room",
        "status": "pin_required",
    }
    assert "mac" not in response.text.lower()
    assert "cert" not in response.text.lower()


@pytest.mark.anyio
async def test_pairing_pin_is_forwarded_once_and_not_echoed(monkeypatch) -> None:
    received = []

    async def finish_pairing(session_id: str, pin: str):
        received.append((session_id, pin))

    monkeypatch.setattr(pairing_routes.pairing_manager, "finish_pairing", finish_pairing)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "test-token"}) as client:
        response = await client.post(
            "/pairing/opaque-session/finish",
            json={"pin": "A1B2C3"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "paired"}
    assert received == [("opaque-session", "A1B2C3")]
    assert "A1B2C3" not in response.text


@pytest.mark.anyio
async def test_expired_pairing_session_fails_closed(monkeypatch) -> None:
    async def finish_pairing(_session_id: str, _pin: str):
        raise PairingSessionNotFoundError

    monkeypatch.setattr(pairing_routes.pairing_manager, "finish_pairing", finish_pairing)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "test-token"}) as client:
        response = await client.post(
            "/pairing/expired/finish",
            json={"pin": "A1B2C3"},
        )

    assert response.status_code == 410


@pytest.mark.anyio
async def test_pairing_payloads_reject_extra_fields() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "test-token"}) as client:
        response = await client.post(
            "/pairing/start",
            json={"config_id": "tv", "host": "tv.local", "private_key": "secret"},
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_discovery_returns_unverified_candidate_not_fake_identity(monkeypatch) -> None:
    async def discover():
        return (UnverifiedRemoteV2Candidate(name="Living Room", host="tv.local", port=6466),)

    monkeypatch.setattr(discovery_routes.remote_v2_discovery, "discover", discover)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "test-token"}) as client:
        response = await client.post("/discover", json={})

    assert response.status_code == 200
    candidate = response.json()["devices"][0]
    assert candidate["verification_status"] == "unverified"
    assert candidate["stable_device_id"] is None
    assert "device_id" not in candidate


@pytest.mark.anyio
async def test_credentials_are_removed_only_by_explicit_forget(monkeypatch) -> None:
    removed = []
    monkeypatch.setattr(pairing_routes.credential_store, "has_credentials", lambda _: True)
    monkeypatch.setattr(
        pairing_routes.credential_store,
        "remove_credentials",
        lambda config_id: removed.append(config_id),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "test-token"}) as client:
        response = await client.delete("/pairing/credentials/forgotten-tv")

    assert response.status_code == 200
    assert response.json()["status"] == "forgotten"
    assert removed == ["forgotten-tv"]
