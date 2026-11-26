from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Protocol

from .extended_api import ExtendedSenseSnapshot, SenseExtendedApi, SenseTimelineEvent
from .schemas import DeviceConfig


class SenseClientError(RuntimeError):
    """Base error exposed by the Sense adapter."""


class SenseAuthenticationError(SenseClientError):
    pass


class SenseMFARequiredError(SenseAuthenticationError):
    pass


class SenseRateLimitError(SenseClientError):
    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class SenseTransientError(SenseClientError):
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


@dataclass(frozen=True, slots=True)
class StoredSenseAuth:
    access_token: str
    refresh_token: str
    user_id: str
    monitor_id: str
    device_id: str


class SenseAuthStore:
    """Minimal mode-0600 token cache on the dedicated PiPhi data volume."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(
            path
            or os.getenv("PIPHI_SENSE_SESSION_STORE", "/var/lib/piphi/sense-session.json")
        )

    def load(self, account_ref: str) -> StoredSenseAuth | None:
        try:
            payload = json.loads(self.path.read_text())
            record = payload.get(account_ref)
            if not isinstance(record, dict):
                return None
            return StoredSenseAuth(**{key: str(record[key]) for key in StoredSenseAuth.__dataclass_fields__})
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            return None

    def save(self, account_ref: str, auth: StoredSenseAuth) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            payload = json.loads(self.path.read_text())
            if not isinstance(payload, dict):
                payload = {}
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            payload = {}
        payload[account_ref] = {
            key: getattr(auth, key) for key in StoredSenseAuth.__dataclass_fields__
        }
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    def remove(self, account_ref: str) -> None:
        try:
            payload = json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            return
        if not isinstance(payload, dict) or payload.pop(account_ref, None) is None:
            return
        if not payload:
            self.path.unlink(missing_ok=True)
            return
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        os.chmod(self.path, 0o600)


class SenseEnergyClient:
    """Small, testable adapter around the unofficial ``sense-energy`` package."""

    def __init__(self, *, auth_store: SenseAuthStore | None = None) -> None:
        self._session = None
        self._sense = None
        self._scale = None
        self._extended: SenseExtendedApi | None = None
        self._extended_enabled = False
        self._auth_store = auth_store or SenseAuthStore()
        self._account_ref = ""
        self._device_id = ""
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

        self._account_ref = sha256(config.email.encode("utf-8")).hexdigest()
        device_id = "piphi" + self._account_ref[:24]
        self._device_id = device_id
        self._session = aiohttp.ClientSession()
        self._sense = ASyncSenseable(client_session=self._session, device_id=device_id)
        self._scale = Scale
        self._extended_enabled = bool(
            config.expose_appliance_activity or config.expose_timeline
        )
        stored = self._auth_store.load(self._account_ref)

        async def authenticate_with_password() -> None:
            try:
                await self._sense.authenticate(config.email, config.secret_password())
            except SenseMFARequiredException as exc:
                code = config.secret_mfa_code()
                if not code:
                    raise SenseMFARequiredError(
                        "Sense requires an MFA code; submit the form again with the current code."
                    ) from exc
                try:
                    await self._sense.validate_mfa(code)
                except SenseAuthenticationException as mfa_exc:
                    raise SenseAuthenticationError("Sense rejected the MFA code.") from mfa_exc
            except SenseAuthenticationException as exc:
                raise SenseAuthenticationError("Sense rejected the email or password.") from exc

        try:
            if stored is not None and stored.device_id == device_id:
                self._sense.load_auth(
                    stored.access_token, stored.user_id, stored.device_id, stored.refresh_token
                )
                self._sense.set_monitor_id(stored.monitor_id)
                try:
                    await self._sense.fetch_devices()
                except SenseAuthenticationException:
                    # A stale persisted token gets exactly one password fallback.
                    self._auth_store.remove(self._account_ref)
                    await authenticate_with_password()
            else:
                await authenticate_with_password()
        except SenseAuthenticationError:
            await self.close()
            raise

        self.monitor_id = str(self._sense.sense_monitor_id)
        self._persist_auth()
        self._extended = SenseExtendedApi(
            self._sense._api_call,
            monitor_id=self.monitor_id,
            user_id=str(self._sense.sense_user_id),
        )

    async def read(self, *, include_trends: bool) -> SenseReading:
        if self._sense is None or self._scale is None:
            raise SenseClientError("Sense client is not authenticated")

        try:
            await self._sense.update_realtime()
            if include_trends:
                await self._sense.get_trend_data(self._scale.DAY)
            if not getattr(self._sense, "_monitor", None):
                await self._sense.get_monitor_data()
        except Exception as exc:
            raise _translate_read_error(exc) from exc
        self._persist_auth()

        extended = ExtendedSenseSnapshot()
        if self._extended is not None and self._extended_enabled:
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
        self._extended_enabled = False

    def _persist_auth(self) -> None:
        if self._sense is None or not self._account_ref or not self.monitor_id and not getattr(self._sense, "sense_monitor_id", None):
            return
        values = {
            "access_token": getattr(self._sense, "sense_access_token", None),
            "refresh_token": getattr(self._sense, "refresh_token", None),
            "user_id": getattr(self._sense, "sense_user_id", None),
            "monitor_id": self.monitor_id or getattr(self._sense, "sense_monitor_id", None),
            "device_id": self._device_id,
        }
        if all(isinstance(value, str) and value for value in values.values()):
            self._auth_store.save(self._account_ref, StoredSenseAuth(**values))


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _bucket_power(
    devices: tuple[SenseDeviceReading, ...], aliases: set[str]
) -> float | None:
    for device in devices:
        if device.device_id.lower() in aliases or device.name.lower() in aliases:
            return device.power_w
    return None


def _translate_read_error(exc: Exception) -> SenseClientError:
    """Classify unofficial-library failures without exposing response bodies."""
    name = type(exc).__name__.lower()
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status in {401, 403} or "auth" in name:
        return SenseAuthenticationError("Sense authentication expired; reauthentication is required.")
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        retry_after = getattr(exc, "retry_after_seconds", None) or getattr(exc, "retry_after", None)
        try:
            bounded_retry_after = min(max(float(retry_after), 1.0), 3600.0)
        except (TypeError, ValueError):
            bounded_retry_after = None
        return SenseRateLimitError(
            "Sense rate limited the unofficial client.",
            retry_after_seconds=bounded_retry_after,
        )
    return SenseTransientError("The unofficial Sense service is temporarily unavailable.")
