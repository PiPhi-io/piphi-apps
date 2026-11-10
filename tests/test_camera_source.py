from __future__ import annotations

import httpx
import pytest

from piphi_camera_stream.main import app
from piphi_camera_stream.schemas import DeviceConfig
from piphi_camera_stream.state import apply_config, registry


@pytest.mark.anyio
async def test_camera_integration_owns_secret_and_exposes_only_private_source_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-token")
    monkeypatch.setenv("PIPHI_CONTAINER_ID", "camera-container")
    registry.entries.clear()
    registry.state_snapshots.clear()
    await apply_config(DeviceConfig(id="front-door", config_id="front-door", source_url="rtsps://user:top-secret@camera.local/live", alias="Front door", preferred_transport="tcp"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        entities = await client.get("/entities")
        state = await client.get("/state")
        unauthorized = await client.get("/v1/cameras/front-door/source")
        source = await client.get(
            "/v1/cameras/front-door/source",
            headers={
                "X-PiPhi-Integration-Token": "runtime-token",
                "X-Container-Id": "camera-container",
            },
        )
    assert "camera_stream" in entities.json()["entities"][0]["capabilities"]
    assert entities.json()["capabilities"]["camera_stream"]["camera"]["contract_version"] == "camera.media.v1"
    assert "top-secret" not in state.text and "camera.local" not in state.text
    assert unauthorized.status_code == 401
    assert source.json()["source_url"] == "rtsps://user:top-secret@camera.local/live"
    assert source.json()["audience"] == "core-sidecar"


@pytest.mark.anyio
async def test_camera_source_fails_closed_without_runtime_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/cameras/front-door/source")
    assert response.status_code == 503


def test_camera_config_rejects_browser_urls_and_control_characters() -> None:
    with pytest.raises(ValueError, match="RTSP"):
        DeviceConfig(id="camera", source_url="https://camera.local/image.jpg")
    with pytest.raises(ValueError, match="RTSP"):
        DeviceConfig(id="camera", source_url="rtsp://camera.local/live\nspoof")


def test_camera_config_rejects_malformed_inline_credentials() -> None:
    with pytest.raises(ValueError, match="username:password@"):
        DeviceConfig(
            id="camera",
            source_url="rtsps://username@passwordcamera.local:322/stream0",
        )


def test_camera_config_accepts_inline_credentials() -> None:
    config = DeviceConfig(
        id="camera",
        source_url="rtsps://username:password@camera.local:322/stream0",
    )

    assert config.source_url.get_secret_value().startswith("rtsps://username:password@")


@pytest.mark.anyio
async def test_camera_source_combines_separate_credentials_and_percent_encodes_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-token")
    monkeypatch.setenv("PIPHI_CONTAINER_ID", "camera-container")
    registry.entries.clear()
    registry.state_snapshots.clear()
    await apply_config(
        DeviceConfig(
            id="doggy-cam",
            config_id="doggy-cam",
            source_url="rtsp://10.0.0.241:554/stream0",
            username="camera user",
            password="p@ss/word",
        )
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        source = await client.get(
            "/v1/cameras/doggy-cam/source",
            headers={
                "X-PiPhi-Integration-Token": "runtime-token",
                "X-Container-Id": "camera-container",
            },
        )
        state = await client.get("/state")

    assert source.status_code == 200
    assert source.json()["source_url"] == (
        "rtsp://camera%20user:p%40ss%2Fword@10.0.0.241:554/stream0"
    )
    assert "camera user" not in state.text
    assert "p@ss/word" not in state.text


@pytest.mark.parametrize(
    ("username", "password"),
    [("camera-user", None), (None, "camera-password")],
)
def test_camera_config_requires_username_and_password_together(
    username: str | None,
    password: str | None,
) -> None:
    with pytest.raises(ValueError, match="username and password together"):
        DeviceConfig(
            id="camera",
            source_url="rtsp://camera.local/live",
            username=username,
            password=password,
        )


def test_camera_config_rejects_separate_and_inline_credentials_together() -> None:
    with pytest.raises(ValueError, match="either separate fields or the URL"):
        DeviceConfig(
            id="camera",
            source_url="rtsp://legacy:secret@camera.local/live",
            username="camera-user",
            password="camera-password",
        )
