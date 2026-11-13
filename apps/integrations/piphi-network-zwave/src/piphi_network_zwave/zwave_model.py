from __future__ import annotations

import base64
import json
import re
from collections import defaultdict
from typing import Any


CAPABILITY_COMMANDS = {
    "switch_state": "set_switch",
    "level_percent": "set_level",
    "lock_state": "set_lock",
    "thermostat_mode": "set_thermostat_mode",
    "thermostat_setpoint_c": "set_thermostat_setpoint",
}


def normalize_snapshot(
    snapshot: dict[str, Any], *, config_id: str, controller_alias: str | None
) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for raw_node in snapshot.get("nodes", []):
        if not isinstance(raw_node, dict):
            continue
        node_id = _integer(raw_node.get("node_id"))
        if node_id is None:
            continue
        values_by_endpoint: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for raw_value in raw_node.get("values", []):
            if isinstance(raw_value, dict) and isinstance(raw_value.get("id"), dict):
                endpoint = _integer(raw_value["id"].get("endpoint")) or 0
                values_by_endpoint[endpoint].append(raw_value)
        if not values_by_endpoint:
            values_by_endpoint[0] = []
        for endpoint, values in sorted(values_by_endpoint.items()):
            entities.append(
                _normalize_endpoint(
                    raw_node,
                    node_id=node_id,
                    endpoint=endpoint,
                    values=values,
                    config_id=config_id,
                    controller_alias=controller_alias,
                )
            )
    return entities


def entity_response(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": model["device_id"],
        "name": model["name"],
        "config_id": model["config_id"],
        "device_id": model["device_id"],
        "entity_type": model["entity_type"],
        "capabilities": model["capabilities"],
        "available_commands": model["available_commands"],
        "dashboard": {
            "allowed_widgets": ["tile", "stat", "button", "gauge"],
            "default_widget": "tile",
        },
        "metadata": model["metadata"],
    }


def resolve_command_value(
    model: dict[str, Any], *, command: str, value: Any
) -> tuple[dict[str, Any], Any]:
    capability = next(
        (name for name, candidate in CAPABILITY_COMMANDS.items() if candidate == command), None
    )
    if not capability:
        raise ValueError("unsupported_value_command")
    descriptor = model.get("writable_values", {}).get(capability)
    if not isinstance(descriptor, dict):
        raise ValueError("capability_is_not_writeable")
    metadata = descriptor.get("metadata") if isinstance(descriptor.get("metadata"), dict) else {}
    return descriptor["id"], _validate_value(command, value, metadata)


def _normalize_endpoint(
    node: dict[str, Any],
    *,
    node_id: int,
    endpoint: int,
    values: list[dict[str, Any]],
    config_id: str,
    controller_alias: str | None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "connected": bool(node.get("ready")),
        "availability": str(node.get("status") or "unknown").lower() not in {"dead", "unknown"},
        "node_id": node_id,
        "endpoint": endpoint,
        "node_status": str(node.get("status") or "unknown"),
    }
    descriptors: list[dict[str, Any]] = []
    writable_values: dict[str, dict[str, Any]] = {}
    for raw_value in values:
        descriptor = _value_descriptor(raw_value)
        if descriptor is None:
            continue
        descriptors.append(descriptor)
        capability = descriptor.get("capability")
        if capability and descriptor["metadata"].get("readable"):
            if capability not in state or not _is_target_value(descriptor["id"]):
                state[capability] = _normalized_value(
                    capability, descriptor["value"], descriptor["metadata"]
                )
        if capability and descriptor["metadata"].get("writeable"):
            writable_values[capability] = descriptor

    capabilities = sorted({"connected", "availability", "node_status", *state.keys()})
    available_commands = [
        {"id": "refresh", "label": "Refresh values", "kind": "action"},
        {"id": "ping_node", "label": "Ping node", "kind": "action"},
        {"id": "request_node_interview", "label": "Interview node", "kind": "action"},
    ]
    for capability in sorted(writable_values):
        command = CAPABILITY_COMMANDS.get(capability)
        if command:
            available_commands.append(
                {"id": command, "label": command.replace("_", " ").title(), "kind": "action"}
            )

    device_id = f"zwave-node-{node_id}-endpoint-{endpoint}"
    node_name = str(node.get("name") or f"Z-Wave node {node_id}").strip()
    name = node_name if endpoint == 0 else f"{node_name} endpoint {endpoint}"
    return {
        "config_id": config_id,
        "device_id": device_id,
        "name": name,
        "entity_type": _entity_type(capabilities),
        "node_id": node_id,
        "endpoint": endpoint,
        "capabilities": capabilities,
        "available_commands": available_commands,
        "state": state,
        "writable_values": writable_values,
        "metadata": {
            "controller_alias": controller_alias,
            "node_id": node_id,
            "endpoint": endpoint,
            "location": node.get("location"),
            "manufacturer_id": node.get("manufacturer_id"),
            "product_type": node.get("product_type"),
            "product_id": node.get("product_id"),
            "firmware_version": node.get("firmware_version"),
            "values": descriptors,
        },
    }


def _value_descriptor(raw_value: dict[str, Any]) -> dict[str, Any] | None:
    value_id = raw_value.get("id")
    metadata = raw_value.get("metadata")
    if not isinstance(value_id, dict) or not isinstance(metadata, dict):
        return None
    if not metadata.get("readable") and not metadata.get("writeable"):
        return None
    capability = _capability_for(value_id, raw_value, metadata)
    return {
        "key": _value_key(value_id),
        "id": value_id,
        "label": str(raw_value.get("label") or value_id.get("property") or "Z-Wave value"),
        "capability": capability,
        "value": raw_value.get("value"),
        "updated_at": raw_value.get("updated_at"),
        "metadata": {
            key: metadata.get(key)
            for key in (
                "type", "readable", "writeable", "stateful", "unit", "min", "max",
                "step", "states", "description"
            )
            if metadata.get(key) is not None
        },
    }


def _capability_for(
    value_id: dict[str, Any], raw_value: dict[str, Any], metadata: dict[str, Any]
) -> str | None:
    command_class = _integer(value_id.get("command_class"))
    prop = _token(value_id.get("property"))
    label = _token(raw_value.get("property_name") or raw_value.get("label"))
    unit = str(metadata.get("unit") or "").strip().lower()
    if command_class == 37 and prop in {"currentvalue", "targetvalue"}:
        return "switch_state"
    if command_class == 38 and prop in {"currentvalue", "targetvalue"}:
        return "level_percent"
    if command_class == 98 and prop in {"currentmode", "targetmode"}:
        return "lock_state"
    if command_class == 64 and "mode" in prop:
        return "thermostat_mode"
    if command_class == 67 and "setpoint" in prop:
        return "thermostat_setpoint_c"
    if command_class == 128:
        if prop == "level":
            return "battery_percent"
        if prop == "islow":
            return "battery_low"
    if command_class == 49:
        if unit in {"°c", "c", "celsius", "°f", "f", "fahrenheit"} or "temperature" in label:
            return "temperature_c"
        if unit in {"%", "percent"} and "humidity" in label:
            return "humidity_percent"
        if unit in {"lx", "lux"}:
            return "illuminance_lux"
        return "multilevel_sensor_value"
    if command_class == 50:
        return {
            "w": "power_w",
            "kw": "power_kw",
            "kwh": "energy_kwh",
            "v": "voltage_v",
            "a": "current_a",
            "hz": "frequency_hz",
        }.get(unit, "meter_value")
    return None


def _normalized_value(capability: str, value: Any, metadata: dict[str, Any]) -> Any:
    unit = str(metadata.get("unit") or "").strip().lower()
    if capability == "temperature_c" and unit in {"°f", "f", "fahrenheit"} and isinstance(value, (int, float)):
        return round((float(value) - 32.0) * 5.0 / 9.0, 3)
    return value


def _is_target_value(value_id: dict[str, Any]) -> bool:
    return _token(value_id.get("property")).startswith("target")


def _validate_value(command: str, value: Any, metadata: dict[str, Any]) -> Any:
    if command == "set_switch":
        if not isinstance(value, bool):
            raise ValueError("value_must_be_boolean")
        return value
    if command in {"set_level", "set_thermostat_setpoint"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("value_must_be_number")
        numeric = float(value)
        minimum = metadata.get("min")
        maximum = metadata.get("max")
        if isinstance(minimum, (int, float)) and numeric < minimum:
            raise ValueError("value_below_minimum")
        if isinstance(maximum, (int, float)) and numeric > maximum:
            raise ValueError("value_above_maximum")
        return numeric
    states = metadata.get("states")
    if command in {"set_lock", "set_thermostat_mode"} and isinstance(states, dict):
        for state_value, label in states.items():
            if value == label or str(value) == str(state_value):
                return int(state_value) if str(state_value).lstrip("-").isdigit() else state_value
        raise ValueError("value_is_not_an_allowed_state")
    raise ValueError("value_type_is_not_supported")


def _value_key(value_id: dict[str, Any]) -> str:
    encoded = json.dumps(value_id, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _entity_type(capabilities: list[str]) -> str:
    for capability, entity_type in (
        ("lock_state", "lock"),
        ("thermostat_mode", "climate"),
        ("switch_state", "switch"),
        ("level_percent", "light"),
        ("temperature_c", "sensor"),
        ("meter_value", "sensor"),
    ):
        if capability in capabilities:
            return entity_type
    return "zwave_device"


def _token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed
