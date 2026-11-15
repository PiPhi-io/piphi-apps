from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

APPS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(APPS / "integrations/piphi-network-passive-ble-monitor/src"))
sys.path.insert(0, str(APPS / "integrations/piphi-network-bermuda-presence/src"))

from piphi_network_bermuda_presence.gateway import BleGatewayClient  # noqa: E402
from piphi_network_passive_ble_monitor.bthome import BTHOME_UUID  # noqa: E402
from piphi_network_passive_ble_monitor.gateway import GatewayClient  # noqa: E402
from piphi_ble_gateway_sidecar.ble_models import Advertisement  # noqa: E402
from piphi_ble_gateway_sidecar.gateway import gateway  # noqa: E402
from piphi_ble_gateway_sidecar.main import app  # noqa: E402


class FakeScanner:
    backend = "fake-winrt"
    adapter = "radio-0"
    receiver_kind = "local"

    async def start(self, mode, callback) -> None:
        self.mode = mode
        self.callback = callback

    async def stop(self) -> None:
        pass


@pytest.mark.anyio
async def test_real_consumers_interoperate_with_gateway_and_preserve_scope(tmp_path: Path) -> None:
    gateway.consumers.clear()
    gateway.sequence = 0
    gateway._checkpoint = []
    gateway._dedup = {}
    gateway.scanner = FakeScanner()
    gateway.secret_path = tmp_path / "key"
    gateway.checkpoint_path = tmp_path / "checkpoint"
    gateway._secret = None
    await gateway.start()
    selected_address = "AA:BB:CC:DD:EE:01"
    selected_handle = gateway._handle(selected_address)
    transport = httpx.ASGITransport(app=app)
    passive = GatewayClient("http://test", "passive-token-1234", transport=transport)
    bermuda = BleGatewayClient("http://test", "bermuda-token-1234", transport=transport)
    try:
        await passive.register("passive", selected_handle)
        await bermuda.register("bermuda", [selected_handle])

        # The protocol UUID alone must not leak an unselected nearby device.
        await gateway.ingest(Advertisement(
            "AA:BB:CC:DD:EE:02", 1_000, -50,
            service_uuids=(BTHOME_UUID,), service_data={BTHOME_UUID: b"\x40\x00\x01"},
        ))
        await gateway.ingest(Advertisement(
            selected_address, 2_000, -60,
            service_uuids=(BTHOME_UUID,), service_data={BTHOME_UUID: b"\x40\x00\x02"},
        ))

        passive_page = await passive.observations("passive", after=0)
        bermuda_page = await bermuda.observations("bermuda", after=0)
        assert [item.device_handle for item in passive_page.observations] == [selected_handle]
        assert [item.device_handle for item in bermuda_page.observations] == [selected_handle]
        assert passive_page.cursor == bermuda_page.cursor == 2
        assert passive_page.receiver_healthy is True

        gateway.receiver_healthy = False
        snapshot = await bermuda.snapshot("bermuda")
        assert snapshot["cursor"] == 2
        assert snapshot["receiver_healthy"] is False
        assert snapshot["receivers"][0]["healthy"] is False
    finally:
        await passive.close()
        await bermuda.close()
        await gateway.stop()


@pytest.mark.anyio
async def test_queue_loss_is_reported_as_a_cursor_gap(tmp_path: Path) -> None:
    gateway.consumers.clear()
    gateway.sequence = 0
    gateway._checkpoint = []
    gateway._dedup = {}
    gateway.scanner = FakeScanner()
    gateway.secret_path = tmp_path / "key"
    gateway.checkpoint_path = tmp_path / "checkpoint"
    gateway._secret = None
    await gateway.start()
    token = "gap-consumer-token"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"}) as client:
        response = await client.put("/v1/ble/consumers/gap", json={
            "schema_version": "piphi.ble.consumer.v1",
            "matcher": {"service_uuids": ["180f"]},
            "queue_capacity": 2,
        })
        assert response.status_code == 200
        for index in range(3):
            await gateway.ingest(Advertisement(
                "AA:BB:CC:DD:EE:03", 10_000 + index * 2_000, -60 - index,
                service_uuids=("180f",),
            ))
        page = await client.get("/v1/ble/observations/gap", params={"after": 0})
        assert page.status_code == 200
        assert page.json()["gap"] is True
        snapshot = await client.get("/v1/ble/snapshot/gap")
        assert snapshot.json()["cursor"] == 3
        assert snapshot.json()["gap"] is False
    await gateway.stop()
