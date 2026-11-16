from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import httpx
import pytest

from piphi_network_android_tv.adb_sidecar_client import AdbSidecarClient
from piphi_network_android_tv.schemas import DeviceConfig

ROOT = Path(__file__).parents[1]
SIDECAR_SRC = ROOT.parents[1] / "services" / "piphi-android-adb-sidecar" / "src"


class FakeController:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "piphi.adb.snapshot.v1",
            "connected": True,
            "authorized": True,
            "lifecycle": "ready",
            "service_available": True,
            "target_id": "opaque-asgi-lease",
            "device_manufacturer": "Example",
            "device_model": "ASGI TV",
            "android_release": "14",
            "android_sdk": "34",
            "queue_depth": 0,
            "queue_capacity": 16,
            "queue_high_water_mark": 1,
            "reconnect_count": 0,
            "request_success_count": 2,
            "request_failure_count": 0,
            "timeout_count": 0,
            "transport_error_count": 0,
            "operation_duration_ms": 1.0,
            "last_error_code": None,
            "config_id": "asgi-tv",
        }

    async def execute(self, request: Any) -> dict[str, Any]:
        if request.command.operation == "property_query":
            return {
                "operation": "property_query",
                "properties": {
                    property_name.value: {
                        "ro.product.manufacturer": "Example",
                        "ro.product.model": "ASGI TV",
                        "ro.build.version.release": "14",
                        "ro.build.version.sdk": "34",
                    }[property_name.value]
                    for property_name in request.command.properties
                },
            }
        self.keys.append(request.command.key.value)
        return {"operation": "key_event", "repeats_completed": 1}


@pytest.mark.anyio
async def test_parent_client_against_real_authenticated_sidecar_asgi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(SIDECAR_SRC))
    monkeypatch.setenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN", "shared-test-token")

    sidecar_app = import_module("piphi_android_adb_sidecar.app")
    config_routes = import_module("piphi_android_adb_sidecar.routes.config")
    adb_routes = import_module("piphi_android_adb_sidecar.routes.sidecar_api")
    controller = FakeController()

    async def apply_config(_config: Any) -> None:
        return None

    async def remove_config(_config_id: str) -> bool:
        return True

    monkeypatch.setattr(config_routes, "apply_config", apply_config)
    monkeypatch.setattr(config_routes, "remove_config", remove_config)
    monkeypatch.setattr(adb_routes, "get_controller", lambda _config_id: controller)
    monkeypatch.setattr(
        adb_routes,
        "get_controller_by_target",
        lambda target_id: controller if target_id == "opaque-asgi-lease" else None,
    )

    http = httpx.AsyncClient(
        base_url="http://sidecar",
        transport=httpx.ASGITransport(app=sidecar_app.create_app()),
    )
    client = AdbSidecarClient(token="shared-test-token", client=http)
    config = DeviceConfig(id="asgi-tv", host="192.0.2.30", transport="adb")

    configured = await client.configure(config)
    refreshed = await client.refresh("asgi-tv", timeout_ms=1_000)
    await client.send_key("asgi-tv", "HOME", timeout_ms=1_000)
    removed = await client.remove("asgi-tv")

    assert configured.model == "ASGI TV"
    assert refreshed.android_sdk == "34"
    assert controller.keys == ["home"]
    assert removed is True
    await http.aclose()
