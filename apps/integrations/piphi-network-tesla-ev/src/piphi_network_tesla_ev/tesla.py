from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


FLEET_API_BASE_URLS = {
    "na": "https://fleet-api.prd.na.vn.cloud.tesla.com",
    "eu": "https://fleet-api.prd.eu.vn.cloud.tesla.com",
    "cn": "https://fleet-api.prd.cn.vn.cloud.tesla.cn",
}


class TeslaAPIError(RuntimeError):
    """Raised when Tesla returns an unusable Fleet API response."""


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_number(*values: Any) -> int | float | None:
    for value in values:
        parsed = _number(value)
        if parsed is not None:
            return parsed
    return None


def resolve_fleet_api_base_url(region: str = "na", override: str | None = None) -> str:
    if override and override.strip():
        return override.rstrip("/")
    return FLEET_API_BASE_URLS.get(region, FLEET_API_BASE_URLS["na"])


@dataclass(slots=True)
class TeslaClient:
    access_token: str
    region: str = "na"
    base_url: str | None = None
    timeout: float = 15.0
    transport: httpx.AsyncBaseTransport | None = None

    async def _request(self, path: str, *, method: str = "GET") -> Any:
        url = f"{resolve_fleet_api_base_url(self.region, self.base_url)}{path}"
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        detail = payload.get("error_description") or payload.get("error") if isinstance(payload, dict) else None
        if response.status_code >= 400 or detail:
            raise TeslaAPIError(
                f"Tesla Fleet API request failed: {detail or f'HTTP {response.status_code}'}"
            )
        if not isinstance(payload, dict) or "response" not in payload:
            raise TeslaAPIError("Tesla Fleet API response was missing a response payload")
        return payload["response"]

    async def list_vehicles(self) -> list[dict[str, Any]]:
        response = await self._request("/api/1/vehicles")
        if not isinstance(response, list):
            return []
        return [normalize_summary(item, fallback_vin="") for item in response if isinstance(item, dict)]

    async def vehicle_summary(self, vin: str) -> dict[str, Any]:
        response = await self._request(f"/api/1/vehicles/{vin}")
        return normalize_summary(_object(response), fallback_vin=vin)

    async def vehicle_data(self, vin: str) -> dict[str, Any]:
        return _object(await self._request(f"/api/1/vehicles/{vin}/vehicle_data"))

    async def wake(self, vin: str) -> dict[str, Any]:
        response = await self._request(f"/api/1/vehicles/{vin}/wake_up", method="POST")
        return normalize_summary(_object(response), fallback_vin=vin)


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


def normalize_summary_state(config: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    vin = str(summary.get("vin") or config["vin"])
    vehicle_state = str(summary.get("state") or "unknown")
    return {
        "deviceId": vin,
        "configId": str(config["configId"]),
        "vin": vin,
        "displayName": str(config.get("vehicle_name") or summary.get("display_name") or vin).strip(),
        "region": str(config.get("region") or "na"),
        "baseUrl": resolve_fleet_api_base_url(str(config.get("region") or "na"), config.get("base_url")),
        "online": vehicle_state == "online",
        "vehicleState": vehicle_state,
        "inService": bool(summary.get("in_service")),
        "includeLocation": config.get("include_location") is not False,
        "batteryLevel": None,
        "usableBatteryLevel": None,
        "chargingState": None,
        "chargeLimitSoc": None,
        "timeToFullChargeHours": None,
        "chargerPowerKw": None,
        "batteryRangeMiles": None,
        "chargeCurrentAmps": None,
        "chargeEnergyAddedKwh": None,
        "pluggedIn": None,
        "insideTempC": None,
        "outsideTempC": None,
        "climateOn": None,
        "isLocked": None,
        "odometerMiles": None,
        "speedMph": None,
        "latitude": None,
        "longitude": None,
        "headingDegrees": None,
        "shiftState": None,
        "lastRefreshAt": None,
        "lastCommandAt": None,
        "lastError": None,
        "source": "summary",
        "summary": summary,
    }


def _plugged_in(charge_state: dict[str, Any], charging_state: str | None) -> bool | None:
    cable = _string(charge_state.get("conn_charge_cable")) or _string(
        charge_state.get("charging_cable_type")
    )
    if cable:
        normalized = cable.lower()
        if normalized in {"<invalid>", "invalid", "none"} or ("no" in normalized and "cable" in normalized):
            return False
        return True
    if charge_state.get("charge_port_door_open") is True:
        return True
    if charging_state:
        normalized = charging_state.lower()
        if normalized == "disconnected":
            return False
        if normalized in {"charging", "complete", "starting", "stopped", "pending", "nopower"}:
            return True
    return None


def normalize_vehicle_data_state(
    config: dict[str, Any], summary: dict[str, Any], vehicle_data: dict[str, Any]
) -> dict[str, Any]:
    state = normalize_summary_state(config, summary)
    charge = _object(vehicle_data.get("charge_state"))
    climate = _object(vehicle_data.get("climate_state"))
    drive = _object(vehicle_data.get("drive_state"))
    vehicle = _object(vehicle_data.get("vehicle_state"))
    charging_state = _string(charge.get("charging_state"))
    include_location = config.get("include_location") is not False
    state.update(
        {
            "online": True,
            "vehicleState": _string(vehicle_data.get("state")) or state["vehicleState"],
            "batteryLevel": _number(charge.get("battery_level")),
            "usableBatteryLevel": _number(charge.get("usable_battery_level")),
            "chargingState": charging_state,
            "chargeLimitSoc": _number(charge.get("charge_limit_soc")),
            "timeToFullChargeHours": _number(charge.get("time_to_full_charge")),
            "chargerPowerKw": _number(charge.get("charger_power")),
            "batteryRangeMiles": _first_number(
                charge.get("battery_range"),
                charge.get("est_battery_range"),
                charge.get("ideal_battery_range"),
            ),
            "chargeCurrentAmps": _first_number(
                charge.get("charger_actual_current"),
                charge.get("charge_current_request"),
                charge.get("charge_current_request_max"),
            ),
            "chargeEnergyAddedKwh": _number(charge.get("charge_energy_added")),
            "pluggedIn": _plugged_in(charge, charging_state),
            "insideTempC": _number(climate.get("inside_temp")),
            "outsideTempC": _number(climate.get("outside_temp")),
            "climateOn": _boolean(climate.get("is_climate_on")),
            "isLocked": _boolean(vehicle.get("locked")),
            "odometerMiles": _number(vehicle.get("odometer")),
            "speedMph": _number(drive.get("speed")),
            "latitude": _number(drive.get("latitude")) if include_location else None,
            "longitude": _number(drive.get("longitude")) if include_location else None,
            "headingDegrees": _number(drive.get("heading")) if include_location else None,
            "shiftState": _string(drive.get("shift_state")),
            "lastRefreshAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source": "vehicle_data",
        }
    )
    return state


def telemetry_metrics(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    mapping = {
        "online": "online",
        "battery_level": "batteryLevel",
        "usable_battery_level": "usableBatteryLevel",
        "charging_state": "chargingState",
        "charge_limit_soc": "chargeLimitSoc",
        "time_to_full_charge_hours": "timeToFullChargeHours",
        "charger_power_kw": "chargerPowerKw",
        "battery_range_miles": "batteryRangeMiles",
        "charge_current_amps": "chargeCurrentAmps",
        "charge_energy_added_kwh": "chargeEnergyAddedKwh",
        "plugged_in": "pluggedIn",
        "inside_temp_c": "insideTempC",
        "outside_temp_c": "outsideTempC",
        "climate_on": "climateOn",
        "is_locked": "isLocked",
        "odometer_miles": "odometerMiles",
        "speed_mph": "speedMph",
        "vehicle_state": "vehicleState",
        "heading_degrees": "headingDegrees",
        "shift_state": "shiftState",
        "last_refresh_at": "lastRefreshAt",
    }
    if state.get("includeLocation"):
        mapping.update({"latitude": "latitude", "longitude": "longitude"})
    metrics = {
        output: state.get(source)
        for output, source in mapping.items()
        if isinstance(state.get(source), (bool, int, float, str))
    }
    units = {
        "battery_level": "%",
        "usable_battery_level": "%",
        "charge_limit_soc": "%",
        "time_to_full_charge_hours": "h",
        "charger_power_kw": "kW",
        "battery_range_miles": "mi",
        "charge_current_amps": "A",
        "charge_energy_added_kwh": "kWh",
        "inside_temp_c": "C",
        "outside_temp_c": "C",
        "odometer_miles": "mi",
        "speed_mph": "mph",
        "heading_degrees": "degrees",
    }
    if state.get("includeLocation"):
        units.update({"latitude": "degrees", "longitude": "degrees"})
    return metrics, units
