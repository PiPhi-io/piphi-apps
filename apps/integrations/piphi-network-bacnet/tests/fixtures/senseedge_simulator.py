from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bacpypes3.app import Application
from bacpypes3.object import AnalogInputObject


async def main() -> None:
    app = Application.from_args(
        SimpleNamespace(
            name="Kaiterra-SE-200",
            instance=1234,
            network=0,
            address="127.0.0.2/8:47809",
            vendoridentifier=999,
            foreign=None,
            ttl=30,
            bbmd=None,
        )
    )
    device = app.device_object
    device.vendorIdentifier = 1307
    device.vendorName = "Kaiterra"
    device.modelName = "Sensedge Mini SE-200"
    device.firmwareRevision = "1.0"
    device.applicationSoftwareVersion = "2.6.5"
    device.protocolVersion = 1
    device.protocolRevision = 14
    device.segmentationSupported = "no-segmentation"
    device.maxApduLengthAccepted = 1476
    device.databaseRevision = 1

    app.add_object(
        AnalogInputObject(
            objectIdentifier=("analog-input", 1),
            objectName="PM2.5",
            presentValue=12.5,
            units="micrograms-per-cubic-meter",
            statusFlags=[0, 0, 0, 0],
            eventState="normal",
            outOfService=False,
            reliability="no-fault-detected",
        )
    )
    app.add_object(
        AnalogInputObject(
            objectIdentifier=("analog-input", 4),
            objectName="Temperature",
            presentValue=22.0,
            units="degrees-celsius",
            statusFlags=[0, 0, 0, 0],
            eventState="normal",
            outOfService=False,
            reliability="no-fault-detected",
        )
    )

    print("senseedge_simulator=ready", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        app.close()


if __name__ == "__main__":
    asyncio.run(main())
