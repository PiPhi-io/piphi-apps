from __future__ import annotations

import json
import stat
from pathlib import Path
from time import monotonic_ns

import httpx
import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot
from piphi_runtime_testkit_python import build_runtime_headers

from piphi_ble_gateway_sidecar import lifecycle
from piphi_ble_gateway_sidecar.ble_models import Advertisement, Matcher
from piphi_ble_gateway_sidecar.bthome_crypto import encrypt_bthome_fixture
from piphi_ble_gateway_sidecar.gateway import Gateway
from piphi_ble_gateway_sidecar.main import app
from piphi_ble_gateway_sidecar.privacy import redact
from piphi_ble_gateway_sidecar.scanner import NoopCapabilityAdapter
from piphi_ble_gateway_sidecar.schemas import DeviceConfig
from piphi_ble_gateway_sidecar import state

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"


class FakeScanner:
    backend = "fake-bluez"
    adapter = "hci-test"
    receiver_kind = "local"

    async def start(self, _mode, _callback) -> None:
        return None

    async def stop(self) -> None:
        return None


@pytest.mark.anyio
async def test_only_health_is_public_and_entities_are_not_fabricated(monkeypatch) -> None:
    state.runtime.auth.update(container_id="", internal_token="")
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runtime") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/diagnostics")).status_code in {401, 503}
        assert (await client.get("/entities")).status_code in {401, 503}

    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "test-token")
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://runtime",
        headers=build_runtime_headers(),
    ) as client:
        assert (await client.get("/entities")).json()["entities"] == []


def test_recursive_redaction_removes_secrets_and_raw_identity() -> None:
    value = {
        "nested": [{"authorization": "canary"}, {"bind_key": "canary"}],
        "device_address": "AA:BB:CC:DD:EE:FF",
        "safe": "value",
    }
    rendered = json.dumps(redact(value))
    assert "canary" not in rendered and "AA:BB" not in rendered
    assert redact(value)["safe"] == "value"


@pytest.mark.anyio
async def test_encrypted_bthome_is_decrypted_per_consumer_without_key_leak(tmp_path: Path) -> None:
    address = "A4:C1:38:12:34:56"
    bind_key = bytes.fromhex("00112233445566778899aabbccddeeff")
    plaintext = bytes.fromhex("400001016402c409")
    encrypted = encrypt_bthome_fixture(address, plaintext, bind_key, bytes.fromhex("01000000"))
    gateway = Gateway(
        FakeScanner(), NoopCapabilityAdapter(),
        secret_path=tmp_path / "key", checkpoint_path=tmp_path / "checkpoint.json",
    )
    await gateway.start()
    handle = gateway._handle(address)
    consumer = await gateway.register(
        "encrypted", "e" * 16,
        Matcher(device_handles=frozenset({handle}), service_uuids=frozenset({BTHOME_UUID})),
        "passive", 4, bind_keys={handle: bind_key},
    )
    await gateway.ingest(Advertisement(
        address, monotonic_ns() // 1_000_000, -55,
        service_uuids=(BTHOME_UUID,), service_data={BTHOME_UUID: encrypted},
    ))
    assert consumer.queue[0]["service_data"][BTHOME_UUID] == plaintext.hex()
    diagnostics = json.dumps(await gateway.diagnostics())
    checkpoint = (tmp_path / "checkpoint.json").read_text()
    assert bind_key.hex() not in diagnostics + checkpoint
    assert address not in diagnostics + checkpoint


@pytest.mark.anyio
async def test_key_and_checkpoint_are_owner_only_and_identity_is_stable(tmp_path: Path) -> None:
    first = Gateway(FakeScanner(), NoopCapabilityAdapter(), secret_path=tmp_path / "key", checkpoint_path=tmp_path / "checkpoint.json")
    await first.start()
    handle = first._handle("AA:BB:CC:DD:EE:FF")
    await first.ingest(Advertisement("AA:BB:CC:DD:EE:FF", monotonic_ns() // 1_000_000, -70))
    await first.stop()
    second = Gateway(FakeScanner(), NoopCapabilityAdapter(), secret_path=tmp_path / "key", checkpoint_path=tmp_path / "checkpoint.json")
    await second.start()
    assert second._handle("AA:BB:CC:DD:EE:FF") == handle
    assert stat.S_IMODE((tmp_path / "key").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "checkpoint.json").stat().st_mode) == 0o600


@pytest.mark.anyio
async def test_core_restart_restores_sidecar_config_and_generation(monkeypatch) -> None:
    config = DeviceConfig(id="gateway", alias="BLE gateway")

    async def fake_rehydrate(**kwargs) -> None:
        snapshot = RuntimeConfigSnapshot(container_id="container", generation=23).model_copy(
            update={"configs": [config]}
        )
        await kwargs["apply_snapshot"](snapshot)

    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", fake_rehydrate)
    await lifecycle.startup_sync("runtime", "client")
    assert state.registry.ids() == ["gateway"]
    assert state.registry.get("gateway")["alias"] == "BLE gateway"
    assert state.runtime.process_state.current_generation == 23
