from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol

from .extended_api import ExtendedSenseSnapshot, SenseExtendedApi, SenseTimelineEvent
from .schemas import DeviceConfig


class SenseClientError(RuntimeError):
    """Base error exposed by the Sense adapter."""


class SenseAuthenticationError(SenseClientError):
    pass


class SenseMFARequiredError(SenseAuthenticationError):
    pass


@dataclass(frozen=True, slots=True)
class SenseDeviceReading:
    device_id: str
    name: str
    icon: str
    power_w: float
    is_on: bool
    daily_energy_kwh: float
    device_type: str | None = None
    first_usage: str | None = None
    timeline_enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class SenseReading:
    monitor_id: str
    time_zone: str
    active_power_w: float
    active_solar_power_w: float
    voltage_v: tuple[float, ...] = ()
    frequency_hz: float = 0.0
    daily_usage_kwh: float = 0.0
    daily_production_kwh: float = 0.0
    daily_from_grid_kwh: float | None = None
    daily_to_grid_kwh: float | None = None
    devices: tuple[SenseDeviceReading, ...] = field(default_factory=tuple)
    always_on_power_w: float | None = None
    other_power_w: float | None = None
    timeline_events: tuple[SenseTimelineEvent, ...] = field(default_factory=tuple)


class SenseClient(Protocol):
    monitor_id: str

    async def authenticate(self, config: DeviceConfig) -> None: ...

    async def read(self, *, include_trends: bool) -> SenseReading: ...

    async def close(self) -> None: ...


class SenseEnergyClient:
    """Small, testable adapter around the unofficial ``sense-energy`` package."""

    def __init__(self) -> None:
        self._session = None
        self._sense = None
        self._scale = None
        self._extended: SenseExtendedApi | None = None
        self.monitor_id = ""

    async def authenticate(self, config: DeviceConfig) -> None:
        # Keep third-party imports here so contract tests can use a fake client
        # without opening a network session or requiring Sense credentials.
        import aiohttp
        from sense_energy import ASyncSenseable
        from sense_energy.sense_api import Scale
        from sense_energy.sense_exceptions import (
            SenseAuthenticationException,
            SenseMFARequiredException,
        )

        device_id = "piphi" + sha256(config.email.encode("utf-8")).hexdigest()[:24]
        self._session = aiohttp.ClientSession()
        self._sense = ASyncSenseable(client_session=self._session, device_id=device_id)
        self._scale = Scale
        try:
            await self._sense.authenticate(config.email, config.secret_password())
        except SenseMFARequiredException as exc:
            code = config.secret_mfa_code()
            if not code:
                await self.close()
                raise SenseMFARequiredError(
                    "Sense requires an MFA code; submit the form again with the current code."
                ) from exc
            try:
                await self._sense.validate_mfa(code)
            except SenseAuthenticationException as mfa_exc:
                await self.close()
                raise SenseAuthenticationError("Sense rejected the MFA code.") from mfa_exc
        except SenseAuthenticationException as exc:
            await self.close()
            raise SenseAuthenticationError("Sense rejected the email or password.") from exc

        self.monitor_id = str(self._sense.sense_monitor_id)
        self._extended = SenseExtendedApi(
            self._sense._api_call,
            monitor_id=self.monitor_id,
            user_id=str(self._sense.sense_user_id),
        )

    async def read(self, *, include_trends: bool) -> SenseReading:
        if self._sense is None or self._scale is None:
            raise SenseClientError("Sense client is not authenticated")

        await self._sense.update_realtime()
        if include_trends:
            await self._sense.get_trend_data(self._scale.DAY)
        if not getattr(self._sense, "_monitor", None):
            await self._sense.get_monitor_data()

        extended = ExtendedSenseSnapshot()
        if self._extended is not None:
            extended = (
                await self._extended.refresh()
                if include_trends
                else self._extended.snapshot
            )
        details = {device.device_id: device for device in extended.appliances}
        devices = tuple(
            SenseDeviceReading(
                device_id=str(device.id),
                name=str(device.name or f"Sense device {device.id}"),
                icon=str(device.icon or "unknown"),
                power_w=float(device.power_w or 0),
                is_on=bool(device.is_on),
                daily_energy_kwh=float(device.energy_kwh.get(self._scale.DAY, 0) or 0),
                device_type=(
                    details[str(device.id)].device_type if str(device.id) in details else None
                ),
                first_usage=(
                    details[str(device.id)].first_usage if str(device.id) in details else None
                ),
                timeline_enabled=(
                    details[str(device.id)].timeline_enabled
                    if str(device.id) in details
                    else None
                ),
            )
            for device in self._sense.devices
        )
        always_on_power_w = extended.always_on_power_w
        if always_on_power_w is None:
            always_on_power_w = _bucket_power(devices, {"always_on", "always on"})
        other_power_w = extended.other_power_w
        if other_power_w is None:
            other_power_w = _bucket_power(devices, {"unknown", "other"})
        return SenseReading(
            monitor_id=self.monitor_id,
            time_zone=str(self._sense.time_zone or ""),
            active_power_w=float(self._sense.active_power or 0),
            active_solar_power_w=float(self._sense.active_solar_power or 0),
            voltage_v=tuple(float(value) for value in (self._sense.active_voltage or [])),
            frequency_hz=float(self._sense.active_frequency or 0),
            daily_usage_kwh=float(self._sense.daily_usage or 0),
            daily_production_kwh=float(self._sense.daily_production or 0),
            daily_from_grid_kwh=_optional_float(self._sense.daily_from_grid),
            daily_to_grid_kwh=_optional_float(self._sense.daily_to_grid),
            devices=devices,
            always_on_power_w=always_on_power_w,
            other_power_w=other_power_w,
            timeline_events=extended.timeline_events,
        )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        self._sense = None
        self._extended = None


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _bucket_power(
    devices: tuple[SenseDeviceReading, ...], aliases: set[str]
) -> float | None:
    for device in devices:
        if device.device_id.lower() in aliases or device.name.lower() in aliases:
            return device.power_w
    return None
