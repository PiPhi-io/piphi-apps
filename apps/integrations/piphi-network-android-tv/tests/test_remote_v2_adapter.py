from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

import piphi_network_android_tv.remote_v2_adapter as adapter_module
from piphi_network_android_tv.remote_v2_adapter import (
    AndroidTVRemoteV2Adapter,
    RemoteV2AuthenticationError,
    RemoteV2CommandError,
    RemoteV2UnavailableError,
)


class FakeRemote:
    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.is_on: bool | None = True
        self.current_app: str | None = "com.example.tv"
        self.volume_info: dict[str, Any] | None = {
            "level": 8,
            "max": 20,
            "muted": False,
        }
        self.device_info: dict[str, str] | None = {
            "manufacturer": "Example",
            "model": "Living Room Display",
            "sw_version": "14",
        }
        self.connected = False
        self.disconnect_count = 0
        self.key_commands: list[tuple[str, str]] = []
        self.callbacks: dict[str, Callable[[Any], None]] = {}
        self.removed_callbacks: list[str] = []
        self.reauth_callback: Callable[[], None] | None = None
        self.generated_credentials = False
        self.pairing_started = False
        self.finished_pin: str | None = None

    async def async_connect(self) -> None:
        self.connected = True

    async def async_get_name_and_mac(self) -> tuple[str, str]:
        return "Living Room", "aa-bb-cc-dd-ee-ff"

    def disconnect(self) -> None:
        self.connected = False
        self.disconnect_count += 1

    def send_key_command(self, key: str, direction: str) -> None:
        self.key_commands.append((key, direction))

    def add_is_on_updated_callback(self, callback: Callable[[bool], None]) -> None:
        self.callbacks["power"] = callback

    def add_current_app_updated_callback(self, callback: Callable[[str], None]) -> None:
        self.callbacks["app"] = callback

    def add_volume_info_updated_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        self.callbacks["volume"] = callback

    def add_is_available_updated_callback(self, callback: Callable[[bool], None]) -> None:
        self.callbacks["available"] = callback

    def remove_is_on_updated_callback(self, callback: Callable[[bool], None]) -> None:
        self.removed_callbacks.append("power")

    def remove_current_app_updated_callback(self, callback: Callable[[str], None]) -> None:
        self.removed_callbacks.append("app")

    def remove_volume_info_updated_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        self.removed_callbacks.append("volume")

    def remove_is_available_updated_callback(self, callback: Callable[[bool], None]) -> None:
        self.removed_callbacks.append("available")

    def keep_reconnecting(self, callback: Callable[[], None]) -> None:
        self.reauth_callback = callback

    async def async_generate_cert_if_missing(self) -> bool:
        self.generated_credentials = True
        return True

    async def async_start_pairing(self) -> None:
        self.pairing_started = True

    async def async_finish_pairing(self, pin: str) -> None:
        self.finished_pin = pin


def make_adapter(fake: FakeRemote) -> AndroidTVRemoteV2Adapter:
    return AndroidTVRemoteV2Adapter(
        host="192.0.2.10",
        certfile="client.crt",
        keyfile="client.key",
        remote_factory=lambda **_kwargs: fake,
    )


def test_connect_returns_authenticated_snapshot_with_stable_identity() -> None:
    fake = FakeRemote()
    adapter = make_adapter(fake)

    snapshot = asyncio.run(adapter.connect())

    assert snapshot.available is True
    assert snapshot.authenticated is True
    assert snapshot.reauth_required is False
    assert snapshot.device is not None
    assert snapshot.device.identity.startswith("android-tv-v2:")
    assert "aa:bb" not in snapshot.device.identity
    assert snapshot.device.name == "Living Room"
    assert snapshot.device.manufacturer == "Example"
    assert snapshot.device.model == "Living Room Display"
    assert snapshot.device.software_version == "14"
    assert snapshot.is_on is True
    assert snapshot.current_app == "com.example.tv"
    assert snapshot.volume is not None
    assert snapshot.volume.level == 8


def test_push_callbacks_emit_immutable_snapshots_and_can_unsubscribe() -> None:
    fake = FakeRemote()
    adapter = make_adapter(fake)
    received = []
    remove = adapter.add_snapshot_callback(received.append)
    asyncio.run(adapter.connect())
    received.clear()

    fake.callbacks["power"](False)
    fake.callbacks["app"]("com.example.player")
    fake.callbacks["volume"]({"level": 0, "max": 20, "muted": True})
    fake.callbacks["available"](False)

    assert [snapshot.is_on for snapshot in received] == [False, False, False, False]
    assert received[1].current_app == "com.example.player"
    assert received[2].volume is not None and received[2].volume.muted is True
    assert received[-1].available is False
    assert received[-1].authenticated is True

    remove()
    fake.callbacks["power"](True)
    assert len(received) == 4


def test_refresh_reads_current_protocol_state_without_changing_identity() -> None:
    fake = FakeRemote()
    adapter = make_adapter(fake)
    original = asyncio.run(adapter.connect())
    fake.is_on = False
    fake.current_app = None
    fake.volume_info = {"level": 4, "max": 20, "muted": False}
    fake.device_info = {
        "manufacturer": "Example",
        "model": "Updated metadata",
        "sw_version": "15",
    }

    refreshed = asyncio.run(adapter.refresh())

    assert refreshed.device is not None and original.device is not None
    assert refreshed.device.identity == original.device.identity
    assert refreshed.device.model == "Updated metadata"
    assert refreshed.is_on is False
    assert refreshed.current_app is None
    assert refreshed.volume is not None and refreshed.volume.level == 4


def test_disconnect_clears_authenticated_availability() -> None:
    fake = FakeRemote()
    adapter = make_adapter(fake)
    asyncio.run(adapter.connect())

    asyncio.run(adapter.disconnect())

    assert adapter.snapshot.available is False
    assert adapter.snapshot.authenticated is False
    assert fake.disconnect_count == 1
    assert set(fake.removed_callbacks) == {"power", "app", "volume", "available"}


def test_only_allowlisted_short_key_commands_are_forwarded() -> None:
    fake = FakeRemote()
    adapter = make_adapter(fake)

    with pytest.raises(RemoteV2UnavailableError):
        asyncio.run(adapter.send_key_command("HOME"))

    asyncio.run(adapter.connect())
    asyncio.run(adapter.send_key_command("keycode_dpad_up"))
    assert fake.key_commands == [("DPAD_UP", "SHORT")]

    for unsafe in ("text:hello", "START_LONG:POWER", "SETTINGS", ""):
        with pytest.raises(RemoteV2CommandError):
            asyncio.run(adapter.send_key_command(unsafe))

    assert fake.key_commands == [("DPAD_UP", "SHORT")]


def test_connect_failure_disconnects_and_remains_unauthenticated() -> None:
    class FailingRemote(FakeRemote):
        async def async_connect(self) -> None:
            raise PermissionError("pairing required")

    fake = FailingRemote()
    adapter = make_adapter(fake)

    with pytest.raises(PermissionError, match="pairing required"):
        asyncio.run(adapter.connect())

    assert adapter.snapshot.available is False
    assert adapter.snapshot.authenticated is False
    assert fake.disconnect_count == 1


def test_invalid_auth_is_mapped_to_actionable_reauthentication_error() -> None:
    InvalidAuth = type("InvalidAuth", (Exception,), {})

    class InvalidAuthRemote(FakeRemote):
        async def async_connect(self) -> None:
            raise InvalidAuth("credentials reset")

    adapter = make_adapter(InvalidAuthRemote())
    with pytest.raises(RemoteV2AuthenticationError, match="no longer authorized"):
        asyncio.run(adapter.connect())


def test_pairing_uses_generated_credentials_and_validates_one_time_pin() -> None:
    fake = FakeRemote()
    adapter = make_adapter(fake)

    name, mac = asyncio.run(adapter.start_pairing())
    assert (name, mac) == ("Living Room", "AA:BB:CC:DD:EE:FF")
    assert fake.generated_credentials is True
    assert fake.pairing_started is True

    with pytest.raises(ValueError, match="six hexadecimal"):
        asyncio.run(adapter.finish_pairing("12345"))
    asyncio.run(adapter.finish_pairing("a1b2c3"))
    assert fake.finished_pin == "A1B2C3"


def test_invalid_auth_callback_marks_reauthentication_required() -> None:
    fake = FakeRemote()
    adapter = make_adapter(fake)
    asyncio.run(adapter.connect())
    assert fake.reauth_callback is not None

    fake.reauth_callback()

    assert adapter.snapshot.available is False
    assert adapter.snapshot.authenticated is False
    assert adapter.snapshot.reauth_required is True


def test_optional_dependency_is_imported_only_when_default_factory_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_dependency(_name: str) -> Any:
        raise ImportError("androidtvremote2")

    monkeypatch.setattr(adapter_module, "import_module", missing_dependency)

    with pytest.raises(RemoteV2UnavailableError, match="not installed"):
        AndroidTVRemoteV2Adapter(
            host="192.0.2.10",
            certfile="client.crt",
            keyfile="client.key",
        )
