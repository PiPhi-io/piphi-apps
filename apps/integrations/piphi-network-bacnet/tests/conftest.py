from __future__ import annotations

import pytest

from piphi_network_bacnet.bacnet_client import DeviceSnapshot, SensorReading
from piphi_network_bacnet.schemas import DeviceConfig
from piphi_network_bacnet.state import reset_runtime_state, set_bacnet_reader


class FakeBacnetReader:
    def __init__(self) -> None:
        self.calls: list[DeviceConfig] = []
        self.closed = False
        self.snapshot = DeviceSnapshot(
            device_instance=1234,
            object_name="Kaiterra-SE-200",
            vendor_id=1307,
            model_name="Sensedge Mini SE-200",
            firmware_revision="1.0",
            application_software_version="2.6.5",
            protocol_version=1,
            protocol_revision=14,
            segmentation_supported="no-segmentation",
            max_apdu_length=1476,
            database_revision=1,
            readings=(
                SensorReading(
                    object_instance=1,
                    object_name="PM2.5",
                    metric="pm2_5_ug_m3",
                    value=12.5,
                    unit="µg/m³",
                    status_flags=[False, False, False, False],
                    reliability="no-fault-detected",
                ),
                SensorReading(
                    object_instance=4,
                    object_name="Temperature",
                    metric="temperature_c",
                    value=22.0,
                    unit="°C",
                    status_flags=[False, False, False, False],
                    reliability="no-fault-detected",
                ),
            ),
        )

    async def read_snapshot(self, config: DeviceConfig) -> DeviceSnapshot:
        self.calls.append(config)
        return self.snapshot

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
async def fake_bacnet_reader():
    reader = FakeBacnetReader()
    set_bacnet_reader(reader)
    yield reader
    await reset_runtime_state()
