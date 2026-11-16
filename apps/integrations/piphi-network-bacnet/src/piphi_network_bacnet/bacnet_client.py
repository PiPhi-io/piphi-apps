from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol

from bacpypes3.app import Application
from bacpypes3.json.util import atomic_encode
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Atomic, ObjectIdentifier, PropertyIdentifier

from .schemas import DeviceConfig


KAITERRA_VENDOR_ID = 1307
MAX_OBJECT_LIST_LENGTH = 64
READ_TIMEOUT_SECONDS = 5.0


class BacnetReadError(RuntimeError):
    """A sanitized failure while reading the bounded BACnet profile."""


@dataclass(frozen=True, slots=True)
class SensorReading:
    object_instance: int
    object_name: str
    metric: str
    value: float
    unit: str
    status_flags: list[bool] = field(default_factory=list)
    reliability: str | None = None
    out_of_service: bool = False


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    device_instance: int
    object_name: str
    vendor_id: int
    model_name: str
    firmware_revision: str
    application_software_version: str
    protocol_version: int
    protocol_revision: int
    segmentation_supported: str
    max_apdu_length: int
    database_revision: int
    readings: tuple[SensorReading, ...]

    @property
    def metrics(self) -> dict[str, float | bool]:
        return {
            "connected": True,
            **{reading.metric: reading.value for reading in self.readings},
        }

    @property
    def units(self) -> dict[str, str]:
        return {reading.metric: reading.unit for reading in self.readings}


class BacnetReader(Protocol):
    async def read_snapshot(self, config: DeviceConfig) -> DeviceSnapshot: ...

    async def close(self) -> None: ...


def _encoded(value: Any) -> Any:
    if isinstance(value, Atomic):
        return atomic_encode(value)
    if isinstance(value, (list, tuple)):
        return [_encoded(item) for item in value]
    return value


def _metric_for_point(instance: int, unit: str) -> tuple[str, str, float] | None:
    fixed: dict[tuple[int, str], tuple[str, str, float]] = {
        (1, "micrograms-per-cubic-meter"): ("pm2_5_ug_m3", "µg/m³", 1.0),
        (2, "micrograms-per-cubic-meter"): ("pm10_ug_m3", "µg/m³", 1.0),
        (3, "parts-per-billion"): ("tvoc_ppb", "ppb", 1.0),
        (3, "micrograms-per-cubic-meter"): ("tvoc_ug_m3", "µg/m³", 1.0),
        (4, "degrees-celsius"): ("temperature_c", "°C", 1.0),
        (4, "degrees-fahrenheit"): ("temperature_c", "°C", 5.0 / 9.0),
        (5, "percent-relative-humidity"): ("humidity_percent", "%", 1.0),
        (6, "parts-per-million"): ("co2_ppm", "ppm", 1.0),
        (8, "percent"): ("km20x_module_8_lifespan_percent", "%", 1.0),
        (9, "percent"): ("km20x_module_9_lifespan_percent", "%", 1.0),
        (10, "parts-per-billion"): ("ozone_ppb", "ppb", 1.0),
        (11, "pascals"): ("differential_pressure_pa", "Pa", 1.0),
        (12, "pascals"): ("flow_speed_pressure_pa", "Pa", 1.0),
        (13, "percent"): ("in_duct_module_lifespan_percent", "%", 1.0),
        (14, "parts-per-billion"): ("no2_ppb", "ppb", 1.0),
        (15, "parts-per-million"): ("co_ppm", "ppm", 1.0),
    }
    return fixed.get((instance, unit))


class BacpypesReader:
    """One bounded BACnet/IP client stack for an explicit local interface."""

    def __init__(self) -> None:
        self._app: Application | None = None
        self._local_address: str | None = None
        self._local_device_instance: int | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._app is not None:
            self._app.close()
        self._app = None
        self._local_address = None
        self._local_device_instance = None

    def _application(self, config: DeviceConfig) -> Application:
        local_address = str(config.local_address)
        local_instance = int(config.local_device_instance)
        if self._app is not None:
            if (
                self._local_address != local_address
                or self._local_device_instance != local_instance
            ):
                raise BacnetReadError(
                    "All active BACnet configurations must share one local address and client instance."
                )
            return self._app

        args = SimpleNamespace(
            name="PiPhi BACnet read-only client",
            instance=local_instance,
            network=0,
            address=local_address,
            vendoridentifier=999,
            foreign=None,
            ttl=30,
            bbmd=None,
        )
        try:
            self._app = Application.from_args(args)
        except Exception as exc:  # BACpypes raises several socket/configuration types.
            raise BacnetReadError("Unable to open the configured BACnet/IP interface.") from exc
        self._local_address = local_address
        self._local_device_instance = local_instance
        return self._app

    async def _read(
        self,
        app: Application,
        address: Address,
        object_identifier: ObjectIdentifier,
        property_name: str,
        array_index: int | None = None,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                app.read_property(
                    address,
                    object_identifier,
                    PropertyIdentifier(property_name),
                    array_index,
                ),
                timeout=READ_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise BacnetReadError(
                f"BACnet read failed for allowlisted property {property_name}."
            ) from exc

    async def _optional_read(
        self,
        app: Application,
        address: Address,
        object_identifier: ObjectIdentifier,
        property_name: str,
    ) -> Any | None:
        try:
            return await self._read(app, address, object_identifier, property_name)
        except BacnetReadError:
            return None

    async def read_snapshot(self, config: DeviceConfig) -> DeviceSnapshot:
        async with self._lock:
            app = self._application(config)
            target = Address(config.target_address)
            try:
                responses = await asyncio.wait_for(
                    app.who_is(
                        int(config.device_instance),
                        int(config.device_instance),
                        target,
                        timeout=3,
                    ),
                    timeout=4,
                )
            except Exception as exc:
                raise BacnetReadError("The configured BACnet device did not answer.") from exc
            if not responses:
                raise BacnetReadError("The configured BACnet device did not answer.")

            device = ObjectIdentifier(("device", int(config.device_instance)))
            required = {}
            for property_name in (
                "object-name",
                "vendor-identifier",
                "model-name",
                "firmware-revision",
                "application-software-version",
                "protocol-version",
                "protocol-revision",
                "segmentation-supported",
                "max-apdu-length-accepted",
                "database-revision",
            ):
                required[property_name] = _encoded(
                    await self._read(app, target, device, property_name)
                )

            vendor_id = int(required["vendor-identifier"])
            model_name = str(required["model-name"])
            normalized_model = model_name.lower().replace(" ", "-")
            if vendor_id != KAITERRA_VENDOR_ID or not any(
                marker in normalized_model for marker in ("se-200", "sensedge-mini")
            ):
                raise BacnetReadError(
                    "The target does not match the Kaiterra SenseEdge Mini profile."
                )

            object_count = int(_encoded(await self._read(app, target, device, "object-list", 0)))
            if object_count < 1 or object_count > MAX_OBJECT_LIST_LENGTH:
                raise BacnetReadError("The BACnet object list exceeds the bounded profile.")

            analog_instances: list[int] = []
            for index in range(1, object_count + 1):
                object_id = await self._read(app, target, device, "object-list", index)
                object_type, object_instance = tuple(object_id)
                if str(object_type) == "analog-input" and int(object_instance) in {
                    1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15
                }:
                    analog_instances.append(int(object_instance))

            readings: list[SensorReading] = []
            for instance in sorted(set(analog_instances)):
                object_id = ObjectIdentifier(("analog-input", instance))
                value = float(_encoded(await self._read(app, target, object_id, "present-value")))
                object_name = str(_encoded(await self._read(app, target, object_id, "object-name")))
                source_unit = str(_encoded(await self._read(app, target, object_id, "units")))
                mapping = _metric_for_point(instance, source_unit)
                if mapping is None:
                    continue
                metric, unit, multiplier = mapping
                if instance == 4 and source_unit == "degrees-fahrenheit":
                    value = (value - 32.0) * multiplier
                else:
                    value *= multiplier
                status_flags_value = await self._optional_read(
                    app, target, object_id, "status-flags"
                )
                reliability_value = await self._optional_read(
                    app, target, object_id, "reliability"
                )
                out_of_service_value = await self._optional_read(
                    app, target, object_id, "out-of-service"
                )
                status_flags = _encoded(status_flags_value) if status_flags_value is not None else []
                readings.append(
                    SensorReading(
                        object_instance=instance,
                        object_name=object_name,
                        metric=metric,
                        value=round(value, 4),
                        unit=unit,
                        status_flags=[bool(item) for item in status_flags],
                        reliability=(
                            str(_encoded(reliability_value))
                            if reliability_value is not None
                            else None
                        ),
                        out_of_service=bool(_encoded(out_of_service_value or False)),
                    )
                )

            return DeviceSnapshot(
                device_instance=int(config.device_instance),
                object_name=str(required["object-name"]),
                vendor_id=vendor_id,
                model_name=model_name,
                firmware_revision=str(required["firmware-revision"]),
                application_software_version=str(required["application-software-version"]),
                protocol_version=int(required["protocol-version"]),
                protocol_revision=int(required["protocol-revision"]),
                segmentation_supported=str(required["segmentation-supported"]),
                max_apdu_length=int(required["max-apdu-length-accepted"]),
                database_revision=int(required["database-revision"]),
                readings=tuple(readings),
            )
