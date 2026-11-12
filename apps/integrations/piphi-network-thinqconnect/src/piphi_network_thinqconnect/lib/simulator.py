from __future__ import annotations

from copy import deepcopy
from typing import Any

from piphi_network_thinqconnect.lib.client import ThinQClientError
from piphi_network_thinqconnect.lib.normalization import normalize_discovered_device


_DEVICES: tuple[dict[str, Any], ...] = (
    {
        "deviceId": "sim-thinq-washer",
        "deviceType": "DEVICE_WASHER",
        "deviceName": "Simulated Laundry Washer",
        "modelName": "ThinQ Front Load",
    },
    {
        "deviceId": "sim-thinq-fridge",
        "deviceType": "DEVICE_REFRIGERATOR",
        "deviceName": "Simulated Kitchen Refrigerator",
        "modelName": "ThinQ French Door",
    },
    {
        "deviceId": "sim-thinq-ac",
        "deviceType": "DEVICE_AIR_CONDITIONER",
        "deviceName": "Simulated Living Room AC",
        "modelName": "ThinQ DualCool",
    },
)

_SNAPSHOTS: dict[str, dict[str, Any]] = {
    "sim-thinq-washer": {
        "status": {"current_state": "RUNNING", "washer_operation_mode": "NORMAL", "remote_control_enabled": True, "remain_hour": 0, "remain_minute": 38, "cycle_count": 128, "online": True},
        "profile": {"main": {"resources": ["run_state", "operation", "timer", "cycle"]}},
        "available_controls": [
            {"method": "start", "parameters": []},
            {"method": "pause", "parameters": []},
            {"method": "stop", "parameters": []},
            {"method": "set_course", "parameters": [{"name": "course", "options": ["NORMAL", "DELICATES", "HEAVY"]}]},
        ],
    },
    "sim-thinq-fridge": {
        "status": {"door_state": "CLOSED", "current_state": "IDLE", "fresh_air_filter_remain_percent": 82, "target_temperature_c": 3, "online": True},
        "profile": {"main": {"resources": ["refrigeration", "door_status", "temperature", "filter_info"]}},
        "available_controls": [
            {"method": "set_target_temperature", "parameters": [{"name": "temperature", "type": "number", "min": 1, "max": 7, "unit": "°C"}]},
            {"method": "set_express_mode", "parameters": [{"name": "express_mode", "options": ["ON", "OFF"]}]},
        ],
    },
    "sim-thinq-ac": {
        "status": {"current_temperature_c": 23.5, "target_temperature_c": 22, "humidity": 46, "pm2": 6.2, "operation": "ON", "mode": "COOL", "wind_strength": 3, "filter_remain_percent": 74, "online": True},
        "profile": {"main": {"resources": ["temperature", "humidity", "operation", "air_flow", "filter_info"]}},
        "available_controls": [
            {"method": "set_operation", "parameters": [{"name": "operation", "options": ["ON", "OFF"]}]},
            {"method": "set_mode", "parameters": [{"name": "mode", "options": ["COOL", "HEAT", "DRY"]}]},
            {"method": "set_target_temperature", "parameters": [{"name": "temperature", "type": "number", "min": 16, "max": 30, "unit": "°C"}]},
            {"method": "set_fan_speed", "parameters": [{"name": "fan_speed", "options": [1, 2, 3, 4]}]},
        ],
    },
}


class SimulatedThinQClient:
    """Deterministic upstream substitute; production normalization stays shared."""

    def __init__(self) -> None:
        # Each simulator client owns its state so commands behave like a real
        # appliance without leaking state between tests or runtime sessions.
        self._snapshots = deepcopy(_SNAPSHOTS)

    async def discover_devices(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [normalize_discovered_device(deepcopy(device)) for device in _DEVICES]

    async def fetch_device_snapshot(self, *, device_id: str, **_kwargs: Any) -> dict[str, Any]:
        raw_device = next((device for device in _DEVICES if device["deviceId"] == device_id), None)
        if raw_device is None or device_id not in self._snapshots:
            raise ThinQClientError(f"Unknown simulated ThinQ device '{device_id}'")
        snapshot = deepcopy(self._snapshots[device_id])
        return {"device": deepcopy(raw_device), **snapshot, "client_id": "piphi-thinq-simulator"}

    async def execute_device_command(self, *, device_id: str, control_method: str, control_params: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        if device_id not in self._snapshots:
            raise ThinQClientError(f"Unknown simulated ThinQ device '{device_id}'")
        status = self._snapshots[device_id]["status"]
        normalized_method = control_method.strip().lower()
        if normalized_method in {"start", "resume"}:
            status["current_state"] = "RUNNING"
        elif normalized_method in {"pause", "hold"}:
            status["current_state"] = "PAUSED"
        elif normalized_method in {"stop", "cancel"}:
            status["current_state"] = "STOPPED"
        elif normalized_method in {"turn_on", "power_on"}:
            status["operation"] = "ON"
            status["current_state"] = "ON"
        elif normalized_method in {"turn_off", "power_off"}:
            status["operation"] = "OFF"
            status["current_state"] = "OFF"

        state_fields = {
            "operation": "operation",
            "mode": "mode",
            "temperature": "target_temperature_c",
            "target_temperature": "target_temperature_c",
            "fan_speed": "wind_strength",
            "humidity": "target_humidity",
            "target_humidity": "target_humidity",
            "brightness": "light_brightness",
            "course": "washer_operation_mode",
        }
        for parameter, value in control_params.items():
            status[state_fields.get(parameter, parameter)] = value

        return {
            "status": "ok",
            "simulated": True,
            "control_method": control_method,
            "control_params": deepcopy(control_params),
            "feedback": "Appliance updated",
        }
