from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from piphi_wyze_camera_service.bridge import BridgeRuntimeConfig, WyzeBridgeSupervisor
from piphi_wyze_camera_service.schemas import WyzeBridgeConfig


def config() -> WyzeBridgeConfig:
    return WyzeBridgeConfig(
        wyze_email="owner@example.com",
        wyze_password="account-secret",
        api_id="api-id-secret",
        api_key="api-key-secret",
        advertised_host="127.0.0.1",
        enabled_camera_names=["Doggy Cam", "Doggy Cam"],
    )


def runtime_config() -> BridgeRuntimeConfig:
    return BridgeRuntimeConfig(
        advertised_host="127.0.0.1",
        enabled_camera_names=("Doggy Cam",),
        stream_password="stream secret",
        web_username="piphi",
        web_password="web secret",
    )


def test_config_normalizes_camera_names_and_redacts_secrets() -> None:
    payload = config()

    assert payload.enabled_camera_names == ["Doggy Cam"]
    assert "account-secret" not in repr(payload)
    assert "api-key-secret" not in repr(payload)


def test_bridge_environment_contains_secrets_but_status_does_not() -> None:
    supervisor = WyzeBridgeSupervisor()
    environment = supervisor._bridge_environment(config(), runtime_config())

    assert environment["WYZE_PASSWORD"] == "account-secret"
    assert environment["API_KEY"] == "api-key-secret"
    status = supervisor.status()
    assert "account-secret" not in repr(status)
    assert "api-key-secret" not in repr(status)
    assert status["state"] == "awaiting_configuration"


def test_camera_normalization_and_source_url() -> None:
    cameras = WyzeBridgeSupervisor._normalize_cameras(
        {
            "doggy-cam": {
                "nickname": "Doggy Cam",
                "product_model": "HL_CAM4",
                "status": "connected",
            }
        }
    )

    assert cameras == [
        {
            "id": "doggy-cam",
            "name": "Doggy Cam",
            "model": "HL_CAM4",
            "online": True,
        }
    ]
    descriptor = WyzeBridgeSupervisor._with_source_url(cameras[0], runtime_config())
    assert descriptor["source_url"] == "rtsp://wb:stream%20secret@127.0.0.1:18554/doggy-cam"


@pytest.mark.asyncio
async def test_reconfigure_stops_previous_process(monkeypatch) -> None:
    process = Mock()
    process.returncode = None
    process.wait = AsyncMock(return_value=0)
    create_process = AsyncMock(return_value=process)
    monkeypatch.setattr("asyncio.create_subprocess_exec", create_process)
    supervisor = WyzeBridgeSupervisor()

    await supervisor.configure(config())
    assert supervisor.running is True
    await supervisor.configure(config())

    process.terminate.assert_called_once()
    assert create_process.await_count == 2


@pytest.mark.asyncio
async def test_stop_clears_runtime_secrets(monkeypatch) -> None:
    process = Mock()
    process.returncode = None
    process.wait = AsyncMock(return_value=0)
    monkeypatch.setattr("asyncio.create_subprocess_exec", AsyncMock(return_value=process))
    supervisor = WyzeBridgeSupervisor()

    await supervisor.configure(config())
    await supervisor.stop()

    assert supervisor.configured is False
    assert supervisor.status()["state"] == "awaiting_configuration"
