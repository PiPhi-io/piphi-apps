from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import SecretStr


FLEET_API_BASE_URLS = {
    "na": "https://fleet-api.prd.na.vn.cloud.tesla.com",
    "eu": "https://fleet-api.prd.eu.vn.cloud.tesla.com",
    "cn": "https://fleet-api.prd.cn.vn.cloud.tesla.cn",
}
MAX_RETRY_AFTER_SECONDS = 3600


class TeslaAPIError(RuntimeError):
    """A categorized Fleet API failure safe to expose without vendor payloads."""

    def __init__(
        self,
        category: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(f"Tesla Fleet API request failed ({category})")
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_number(*values: Any) -> int | float | None:
    return next((_number(value) for value in values if _number(value) is not None), None)


def resolve_fleet_api_base_url(region: str = "na", override: str | None = None) -> str:
    if region not in FLEET_API_BASE_URLS:
        raise ValueError(f"Unsupported Tesla Fleet API region: {region}")
    expected = FLEET_API_BASE_URLS[region]
    if override is not None and override.rstrip("/") != expected:
        raise ValueError("Fleet API endpoint overrides are not permitted")
    return expected


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return min(MAX_RETRY_AFTER_SECONDS, max(0, int(value)))
    except ValueError:
        try:
            return min(
                MAX_RETRY_AFTER_SECONDS,
                max(0, int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())),
            )
        except (TypeError, ValueError, OverflowError):
            return None


def _classify_failure(status: int, payload: dict[str, Any]) -> str:
    detail = str(payload.get("error_description") or payload.get("error") or "").lower()
    if status == 401:
        return "authentication_required"
    if status == 403:
        return "scope_or_consent_denied"
    if status == 408:
        return "request_timeout"
    if status == 421:
        return "wrong_region"
    if status == 429:
        return "rate_limited"
    if "billing" in detail or "payment" in detail:
        return "billing_suspended"
    if status >= 500:
        return "vendor_unavailable"
    return "request_rejected"


@dataclass(slots=True)
class TeslaClient:
    access_token: SecretStr | str
    region: str = "na"
    timeout: float = 15.0
    transport: httpx.AsyncBaseTransport | None = None

    async def _request(self, path: str, *, method: str = "GET") -> Any:
        token = self.access_token.get_secret_value() if isinstance(self.access_token, SecretStr) else self.access_token
        url = f"{resolve_fleet_api_base_url(self.region)}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise TeslaAPIError("request_timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise TeslaAPIError("transport_unavailable", retryable=True) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        body = payload if isinstance(payload, dict) else {}
        if response.status_code >= 400 or body.get("error") or body.get("error_description"):
            category = _classify_failure(response.status_code, body)
            raise TeslaAPIError(
                category,
                status_code=response.status_code,
                retryable=response.status_code in {408, 429} or response.status_code >= 500,
                retry_after_seconds=_retry_after(response),
            )
        if "response" not in body:
            raise TeslaAPIError("invalid_response")
        return body["response"]

    async def list_vehicles(self) -> list[dict[str, Any]]:
        response = await self._request("/api/1/vehicles")
        return [normalize_summary(item, fallback_vin="") for item in response if isinstance(item, dict)] if isinstance(response, list) else []

    async def vehicle_summary(self, vin: str) -> dict[str, Any]:
        return normalize_summary(_object(await self._request(f"/api/1/vehicles/{vin}")), fallback_vin=vin)

    async def vehicle_data(self, vin: str) -> dict[str, Any]:
        return _object(await self._request(f"/api/1/vehicles/{vin}/vehicle_data"))

    async def wake(self, vin: str) -> dict[str, Any]:
        return normalize_summary(_object(await self._request(f"/api/1/vehicles/{vin}/wake_up", method="POST")), fallback_vin=vin)


def normalize_summary(value: dict[str, Any], *, fallback_vin: str) -> dict[str, Any]:
    identifier = value.get("id")
    return {
        "id": identifier if isinstance(identifier, (int, str)) else None,
        "vehicle_id": _number(value.get("vehicle_id")),
        "vin": str(value.get("vin") or fallback_vin),
        "display_name": _string(value.get("display_name")),
        "state": _string(value.get("state")),
        "in_service": _boolean(value.get("in_service")),
    }


DETAIL_FIELDS = (
    "batteryLevel", "usableBatteryLevel", "chargingState", "chargeLimitSoc",
    "timeToFullChargeHours", "chargerPowerKw", "batteryRangeMiles", "chargeCurrentAmps",
    "chargeEnergyAddedKwh", "pluggedIn", "insideTempC", "outsideTempC", "climateOn",
    "isLocked", "odometerMiles", "speedMph", "latitude", "longitude", "headingDegrees", "shiftState",
)


def normalize_summary_state(
    config: dict[str, Any], summary: dict[str, Any], previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    vehicle_state = str(summary.get("state") or "unknown")
    prior = previous or {}
    state = {
        "deviceId": str(config["device_id"]),
        "configId": str(config["configId"]),
        "displayName": str(config.get("vehicle_name") or summary.get("display_name") or "Tesla vehicle").strip(),
        "region": str(config.get("region") or "na"),
        "online": vehicle_state == "online",
        "reachable": vehicle_state in {"online", "asleep"},
        "vehicleState": vehicle_state,
        "inService": bool(summary.get("in_service")),
        "includeLocation": config.get("include_location") is True,
        "lastRefreshAt": prior.get("lastRefreshAt"),
        "lastCheckedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "lastCommandAt": prior.get("lastCommandAt"),
        "errorCategory": None,
        "dataQuality": "last_known" if previous else "summary_only",
        "stale": bool(previous),
        "source": "summary",
    }
    for field in DETAIL_FIELDS:
        state[field] = prior.get(field)
    if not state["includeLocation"]:
        for field in ("latitude", "longitude", "headingDegrees", "speedMph"):
            state[field] = None
    return state


def _timestamp(*blocks: dict[str, Any]) -> str:
    timestamps = [_number(block.get("timestamp")) for block in blocks]
    latest = max((value for value in timestamps if value is not None), default=None)
    when = datetime.fromtimestamp(latest / 1000, UTC) if latest and latest > 10_000_000_000 else datetime.now(UTC)
    return when.isoformat().replace("+00:00", "Z")


def _plugged_in(charge_state: dict[str, Any], charging_state: str | None) -> bool | None:
    cable = _string(charge_state.get("conn_charge_cable")) or _string(charge_state.get("charging_cable_type"))
    if cable:
        normalized = cable.lower()
        return False if normalized in {"<invalid>", "invalid", "none"} or ("no" in normalized and "cable" in normalized) else True
    if charge_state.get("charge_port_door_open") is True:
        return True
    if charging_state:
        if charging_state.lower() == "disconnected":
            return False
        if charging_state.lower() in {"charging", "complete", "starting", "stopped", "pending", "nopower"}:
            return True
    return None


def normalize_vehicle_data_state(config: dict[str, Any], summary: dict[str, Any], vehicle_data: dict[str, Any]) -> dict[str, Any]:
    state = normalize_summary_state(config, summary)
    charge = _object(vehicle_data.get("charge_state")); climate = _object(vehicle_data.get("climate_state"))
    drive = _object(vehicle_data.get("drive_state")); vehicle = _object(vehicle_data.get("vehicle_state"))
    charging_state = _string(charge.get("charging_state")); include_location = config.get("include_location") is True
    state.update({
        "online": True, "reachable": True, "vehicleState": _string(vehicle_data.get("state")) or state["vehicleState"],
        "batteryLevel": _number(charge.get("battery_level")), "usableBatteryLevel": _number(charge.get("usable_battery_level")),
        "chargingState": charging_state, "chargeLimitSoc": _number(charge.get("charge_limit_soc")),
        "timeToFullChargeHours": _number(charge.get("time_to_full_charge")), "chargerPowerKw": _number(charge.get("charger_power")),
        "batteryRangeMiles": _first_number(charge.get("battery_range"), charge.get("est_battery_range"), charge.get("ideal_battery_range")),
        "chargeCurrentAmps": _first_number(charge.get("charger_actual_current"), charge.get("charge_current_request"), charge.get("charge_current_request_max")),
        "chargeEnergyAddedKwh": _number(charge.get("charge_energy_added")), "pluggedIn": _plugged_in(charge, charging_state),
        "insideTempC": _number(climate.get("inside_temp")), "outsideTempC": _number(climate.get("outside_temp")),
        "climateOn": _boolean(climate.get("is_climate_on")), "isLocked": _boolean(vehicle.get("locked")),
        "odometerMiles": _number(vehicle.get("odometer")), "speedMph": _number(drive.get("speed")) if include_location else None,
        "latitude": _number(drive.get("latitude")) if include_location else None, "longitude": _number(drive.get("longitude")) if include_location else None,
        "headingDegrees": _number(drive.get("heading")) if include_location else None, "shiftState": _string(drive.get("shift_state")),
        "lastRefreshAt": _timestamp(charge, climate, drive, vehicle), "dataQuality": "fresh", "stale": False, "source": "vehicle_data",
    })
    return state


def telemetry_metrics(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    mapping = {
        "online": "online", "battery_level": "batteryLevel", "usable_battery_level": "usableBatteryLevel",
        "charging_state": "chargingState", "charge_limit_soc": "chargeLimitSoc", "time_to_full_charge_hours": "timeToFullChargeHours",
        "charger_power_kw": "chargerPowerKw", "battery_range_miles": "batteryRangeMiles", "charge_current_amps": "chargeCurrentAmps",
        "charge_energy_added_kwh": "chargeEnergyAddedKwh", "plugged_in": "pluggedIn", "inside_temp_c": "insideTempC",
        "outside_temp_c": "outsideTempC", "climate_on": "climateOn", "is_locked": "isLocked", "odometer_miles": "odometerMiles",
        "vehicle_state": "vehicleState", "shift_state": "shiftState", "last_refresh_at": "lastRefreshAt",
    }
    if state.get("includeLocation"):
        mapping.update({"speed_mph": "speedMph", "heading_degrees": "headingDegrees", "latitude": "latitude", "longitude": "longitude"})
    metrics = {output: state.get(source) for output, source in mapping.items() if isinstance(state.get(source), (bool, int, float, str))}
    units = {"battery_level": "%", "usable_battery_level": "%", "charge_limit_soc": "%", "time_to_full_charge_hours": "h", "charger_power_kw": "kW", "battery_range_miles": "mi", "charge_current_amps": "A", "charge_energy_added_kwh": "kWh", "inside_temp_c": "C", "outside_temp_c": "C", "odometer_miles": "mi"}
    if state.get("includeLocation"):
        units.update({"speed_mph": "mph", "heading_degrees": "degrees", "latitude": "degrees", "longitude": "degrees"})
    return metrics, units
