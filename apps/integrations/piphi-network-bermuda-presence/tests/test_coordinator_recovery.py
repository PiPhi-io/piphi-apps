from __future__ import annotations

from typing import Any, cast

import pytest

from piphi_network_bermuda_presence.coordinator import PresenceCoordinator
from piphi_network_bermuda_presence.gateway import BleGatewayClient, CursorGap
from piphi_network_bermuda_presence.schemas import DeviceConfig


class GapThenSnapshotClient:
    async def observations(self, _consumer_id: str, *, after: int, limit: int = 256) -> Any:
        raise CursorGap("gap")

    async def snapshot(self, _consumer_id: str) -> dict[str, Any]:
        return {
            "cursor": 12,
            "topology_revision": 2,
            "receivers": [{"receiver_id": "r1", "area_id": "room", "area_name": "Room", "healthy": True}],
            "observations": [{
                "schema_version": "piphi.ble.observation.v1", "sequence": 12, "device_handle": "ble_00000000000000000000000000000001",
                "receiver_id": "r1", "receiver_kind": "proxy", "observed_monotonic_ms": 12_000,
                "ingested_at": "2099-01-01T00:00:00Z", "replayed": True, "rssi": -50,
                "connectable": False, "address_type": "random", "service_uuids": [],
            }],
        }


@pytest.mark.anyio
async def test_cursor_gap_recovers_snapshot_without_unselected_entities() -> None:
    config = DeviceConfig.model_validate({
        "id": "cfg", "gateway_url": "https://gateway.test", "api_token": "token", "consumer_id": "consumer",
        "selected_device_handles": ["ble_00000000000000000000000000000001"],
        "receivers": [{"receiver_id": "r1", "area_id": "room", "area_name": "Room"}],
    })
    coordinator = PresenceCoordinator(config, lambda *_: None, cast(BleGatewayClient, GapThenSnapshotClient()))
    await coordinator.poll_once()
    assert coordinator.cursor == 12
    assert coordinator.engine.topology_revision == 2
    assert [entity["device_handle"] for entity in coordinator.entity_states()] == ["ble_00000000000000000000000000000001"]
