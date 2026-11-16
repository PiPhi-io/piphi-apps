from __future__ import annotations

import asyncio

import httpx
import pytest
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import ValidationError

from piphi_network_bacnet.bacnet_client import BacnetReadError, BacpypesReader
from piphi_network_bacnet.main import app
from piphi_network_bacnet.schemas import DeviceConfig


def config(**updates) -> DeviceConfig:
    values = {
        "id": "senseedge-test",
        "host": "192.0.2.20",
        "device_instance": 1234,
        "local_address": "192.0.2.10/24",
    }
    values.update(updates)
    return DeviceConfig.model_validate(values)


class FakeApplication:
    def __init__(self, *, vendor_id: int = 1307) -> None:
        self.vendor_id = vendor_id
        self.requests: list[tuple[str, str, int | None]] = []

    async def who_is(self, low, high, address, timeout):
        assert low == high == 1234
        assert str(address) == "192.0.2.20"
        assert timeout == 3
        return [object()]

    async def read_property(self, address, object_id, property_id, array_index=None):
        del address
        object_type, instance = tuple(object_id)
        object_type = str(object_type)
        prop = str(property_id)
        self.requests.append((f"{object_type},{instance}", prop, array_index))
        if object_type == "device":
            values = {
                "object-name": "Kaiterra-SE-200",
                "vendor-identifier": self.vendor_id,
                "model-name": "Sensedge Mini SE-200",
                "firmware-revision": "1.0",
                "application-software-version": "2.6.5",
                "protocol-version": 1,
                "protocol-revision": 14,
                "segmentation-supported": "no-segmentation",
                "max-apdu-length-accepted": 1476,
                "database-revision": 5,
            }
            if prop == "object-list":
                objects = [
                    ObjectIdentifier(("device", 1234)),
                    ObjectIdentifier(("analog-input", 1)),
                    ObjectIdentifier(("analog-input", 4)),
                    ObjectIdentifier(("analog-input", 7)),
                ]
                return len(objects) if array_index == 0 else objects[array_index - 1]
            return values[prop]
        point_values = {
            (1, "present-value"): 8.5,
            (1, "object-name"): "PM2.5",
            (1, "units"): "micrograms-per-cubic-meter",
            (4, "present-value"): 77.0,
            (4, "object-name"): "Temperature",
            (4, "units"): "degrees-fahrenheit",
            (1, "status-flags"): [False, False, False, False],
            (4, "status-flags"): [False, False, False, False],
            (1, "reliability"): "no-fault-detected",
            (4, "reliability"): "no-fault-detected",
            (1, "out-of-service"): False,
            (4, "out-of-service"): False,
        }
        return point_values[(int(instance), prop)]

    def close(self):
        return None


@pytest.mark.anyio
async def test_profile_reads_only_allowlisted_present_objects_and_normalizes_units() -> None:
    reader = BacpypesReader()
    reader._app = FakeApplication()  # type: ignore[assignment]
    reader._local_address = "192.0.2.10/24"
    reader._local_device_instance = 4194000

    snapshot = await reader.read_snapshot(config())

    assert snapshot.vendor_id == 1307
    assert snapshot.protocol_revision == 14
    assert snapshot.metrics == {
        "connected": True,
        "pm2_5_ug_m3": 8.5,
        "temperature_c": 25.0,
    }
    assert not any(request[0] == "analog-input,7" for request in reader._app.requests)


@pytest.mark.anyio
async def test_profile_rejects_non_kaiterra_target() -> None:
    reader = BacpypesReader()
    reader._app = FakeApplication(vendor_id=999)  # type: ignore[assignment]
    reader._local_address = "192.0.2.10/24"
    reader._local_device_instance = 4194000

    with pytest.raises(BacnetReadError, match="does not match"):
        await reader.read_snapshot(config())


def test_config_requires_literal_ipv4_and_distinct_instances() -> None:
    with pytest.raises(ValidationError):
        config(host="senseedge.local")
    with pytest.raises(ValidationError):
        config(local_device_instance=1234)
    with pytest.raises(ValidationError):
        config(host="198.51.100.20")


@pytest.mark.anyio
async def test_config_poll_negotiates_runtime_entity_capabilities(fake_bacnet_reader) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/config",
            json=config().model_dump(mode="json"),
        )
        assert response.status_code == 200
        for _ in range(20):
            entities = (await client.get("/entities")).json()["entities"]
            if entities and "pm2_5_ug_m3" in entities[0]["capabilities"]:
                break
            await asyncio.sleep(0)
        assert entities[0]["capabilities"] == [
            "connected",
            "pm2_5_ug_m3",
            "temperature_c",
            "refresh",
        ]
        state = (await client.get("/state")).json()
        serialized = str(state)
        assert "192.0.2.20" not in serialized
        assert "192.0.2.10" not in serialized
