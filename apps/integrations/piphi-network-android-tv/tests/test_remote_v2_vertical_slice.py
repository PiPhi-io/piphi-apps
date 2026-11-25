from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from piphi_runtime_testkit_python import build_runtime_headers

from piphi_network_android_tv import state as runtime_state
from piphi_network_android_tv.device_sessions import DeviceSessionManager
from piphi_network_android_tv.main import app
from piphi_network_android_tv.remote_v2_adapter import (
    RemoteV2Device,
    RemoteV2Snapshot,
    RemoteV2Volume,
)
from piphi_network_android_tv.remote_v2_pairing import (
    RemoteV2CredentialStore,
    RemoteV2PairingManager,
)
from piphi_network_android_tv.routes import pairing as pairing_routes
from piphi_network_android_tv.runtime_service import AndroidTVRuntimeService


class FakePairingAdapter:
    def __init__(self, *, certfile: str, keyfile: str, **_kwargs: Any) -> None:
        self.certfile = Path(certfile)
        self.keyfile = Path(keyfile)

    async def start_pairing(self) -> tuple[str, str]:
        self.certfile.write_text("test certificate")
        self.keyfile.write_text("test private key")
        return "Living Room", "AA:BB:CC:DD:EE:FF"

    async def finish_pairing(self, pin: str) -> None:
        assert pin == "A1B2C3"

    async def disconnect(self) -> None:
        return None


class FakeConnectedAdapter:
    def __init__(self, **_kwargs: Any) -> None:
        self.callback = None
        self.keys: list[str] = []
        self.result = RemoteV2Snapshot(
            available=True,
            authenticated=True,
            reauth_required=False,
            device=RemoteV2Device(
                identity="android-tv-v2:stable-opaque-id",
                name="Living Room",
                manufacturer="Example",
                model="TV",
                software_version="14",
            ),
            is_on=True,
            current_app="launcher",
            volume=RemoteV2Volume(level=10, maximum=20, muted=False),
        )

    @property
    def snapshot(self) -> RemoteV2Snapshot:
        return self.result

    def add_snapshot_callback(self, callback):
        self.callback = callback
        return lambda: None

    async def connect(self) -> RemoteV2Snapshot:
        return self.result

    async def disconnect(self) -> None:
        return None

    async def refresh(self) -> RemoteV2Snapshot:
        if self.callback:
            self.callback(self.result)
        return self.result

    async def send_key_command(self, key: str) -> None:
        self.keys.append(key)


@pytest.mark.anyio
async def test_pair_configure_observe_control_remove_and_forget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RemoteV2CredentialStore(tmp_path / "credentials")
    pairing_manager = RemoteV2PairingManager(
        store,
        adapter_factory=FakePairingAdapter,
    )
    connected_adapters: list[FakeConnectedAdapter] = []

    def adapter_factory(**kwargs: Any) -> FakeConnectedAdapter:
        adapter = FakeConnectedAdapter(**kwargs)
        connected_adapters.append(adapter)
        return adapter

    service: AndroidTVRuntimeService

    def receive(config_id: str, snapshot: RemoteV2Snapshot) -> None:
        service.receive_snapshot(config_id, snapshot)

    sessions = DeviceSessionManager(adapter_factory, receive)

    def credential_paths(config_id: str):
        paths = store.paths_for(config_id, create=True)
        return paths.certfile, paths.keyfile

    service = AndroidTVRuntimeService(
        registry=runtime_state.registry,
        sessions=sessions,
        credentials=credential_paths,
    )
    monkeypatch.setattr(runtime_state, "android_tv_service", service)
    monkeypatch.setattr(runtime_state, "pairing_manager", pairing_manager)
    monkeypatch.setattr(runtime_state, "credential_store", store)
    monkeypatch.setattr(pairing_routes, "pairing_manager", pairing_manager)
    monkeypatch.setattr(pairing_routes, "credential_store", store)

    config_id = "vertical-slice-tv"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "test-token"}) as client:
        started = await client.post(
            "/pairing/start",
            json={"config_id": config_id, "host": "tv.local"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]
        finished = await client.post(
            f"/pairing/{session_id}/finish",
            json={"pin": "A1B2C3"},
        )
        assert finished.status_code == 200

        configured = await client.post(
            "/config",
            json={
                "id": config_id,
                "host": "tv.local",
                "alias": "Living Room",
                "enable_controls": True,
            },
            headers=build_runtime_headers(),
        )
        assert configured.status_code == 200

        entities = (await client.get("/entities")).json()["entities"]
        assert entities[0]["device_id"] == "android-tv-v2:stable-opaque-id"
        state = (await client.get("/state")).json()["entries"][config_id]["latest_state"]
        assert state["connected"] is True
        assert state["volume_level_percent"] == 50
        assert "host" not in state

        command = await client.post(
            "/command",
            json={
                "contract_version": "automation.runtime.command.v1",
                "command": "send_key",
                "target": {"config_id": config_id},
                "params": {"key": "HOME"},
                "capability": "device.send_key",
            },
        )
        assert command.status_code == 200
        assert command.json()["status"] == "success"
        assert connected_adapters[0].keys == ["HOME"]

        diagnostics = (await client.get("/diagnostics")).json()
        assert "tv.local" not in str(diagnostics)
        assert diagnostics["diagnostics"]["connected_count"] == 1

        removed = await client.post(f"/deconfigure/{config_id}")
        assert removed.status_code == 200
        forgotten = await client.delete(f"/pairing/credentials/{config_id}")
        assert forgotten.status_code == 200
        assert store.has_credentials(config_id) is False
