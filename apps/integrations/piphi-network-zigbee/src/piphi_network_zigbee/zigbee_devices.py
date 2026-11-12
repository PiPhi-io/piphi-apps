from __future__ import annotations

from typing import Any


PROPERTY_CAPABILITY_MAP = {
    "action": "action",
    "battery": "battery_percent",
    "battery_low": "battery_low",
    "brightness": "brightness_percent",
    "carbon_monoxide": "carbon_monoxide",
    "color_temp": "color_temperature_mired",
    "contact": "contact_open",
    "current": "current_a",
    "energy": "energy_kwh",
    "gas": "gas",
    "humidity": "humidity_percent",
    "illuminance": "illuminance_lux",
    "linkquality": "linkquality",
    "occupancy": "occupancy",
    "position": "position_percent",
    "power": "power_w",
    "presence": "occupancy",
    "pressure": "pressure_hpa",
    "smoke": "smoke",
    "state": "state",
    "tamper": "tamper",
    "temperature": "temperature_c",
    "voltage": "voltage_v",
    "water_leak": "water_leak",
}

CAPABILITY_COMMANDS = {
    "brightness_percent": "set_brightness",
    "color_temperature_mired": "set_color_temperature",
    "state": "set_state",
}


def normalize_device_id(value: str) -> str:
    return (
        str(value or "zigbee-device")
        .strip()
        .replace("/", "_")
        .replace(" ", "_")
        .replace(":", "")
        .lower()
    )


def infer_capabilities(definition: dict[str, Any] | None) -> list[str]:
    capabilities = {"connected", "availability", "refresh"}
    for expose in normalize_exposes(definition):
        capability = expose.get("capability")
        if capability:
            capabilities.add(str(capability))
    return sorted(capabilities)


def normalize_exposes(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    exposes: list[dict[str, Any]] = []
    for expose in _iter_exposes((definition or {}).get("exposes")):
        property_name = str(expose.get("property") or expose.get("name") or "").strip()
        if not property_name:
            continue
        exposes.append(_normalize_expose(expose, property_name))
    return exposes


def capability_metadata_from_exposes(exposes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for expose in exposes:
        capability = expose.get("capability")
        if not capability or capability in metadata:
            continue
        metadata[str(capability)] = {
            key: value
            for key, value in expose.items()
            if key
            in {
                "property",
                "name",
                "type",
                "unit",
                "min",
                "max",
                "values",
                "access",
                "endpoint",
                "description",
                "value_on",
                "value_off",
                "value_toggle",
            }
            and value is not None
        }
    return metadata


def available_commands_for(
    capabilities: list[str],
    exposes: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    commands = [{"id": "refresh", "label": "Refresh", "kind": "action"}]
    writable_capabilities = {
        str(expose.get("capability"))
        for expose in (exposes or [])
        if expose.get("capability")
        and isinstance(expose.get("access"), dict)
        and expose["access"].get("set") is True
    }
    for capability in sorted(capabilities):
        command = CAPABILITY_COMMANDS.get(capability)
        # Legacy configurations did not persist expose metadata. Preserve their
        # existing controls, but when metadata is present fail closed unless the
        # matching Zigbee2MQTT expose is explicitly writable.
        if command and (exposes is None or capability in writable_capabilities):
            commands.append(
                {
                    "id": command,
                    "label": _format_label(command),
                    "kind": "action",
                }
            )
    return commands


def normalize_zigbee2mqtt_device(
    raw_device: dict[str, Any],
    *,
    default_base_topic: str = "zigbee2mqtt",
    sidecar_base_url: str | None = None,
) -> dict[str, Any]:
    definition = raw_device.get("definition") if isinstance(raw_device.get("definition"), dict) else {}
    friendly_name = str(
        raw_device.get("friendly_name")
        or raw_device.get("friendlyName")
        or raw_device.get("name")
        or raw_device.get("ieee_address")
        or raw_device.get("ieeeAddress")
        or "zigbee-device"
    ).strip()
    ieee_address = str(raw_device.get("ieee_address") or raw_device.get("ieeeAddress") or "").strip() or None
    model_id = str(definition.get("model") or raw_device.get("model_id") or raw_device.get("modelId") or "").strip() or None
    vendor = str(definition.get("vendor") or raw_device.get("vendor") or "").strip() or None
    exposes = normalize_exposes(definition)
    capabilities = infer_capabilities(definition)
    device_id = normalize_device_id(ieee_address or friendly_name)
    return {
        "id": device_id,
        "config_id": device_id,
        "device_id": device_id,
        "friendly_name": friendly_name,
        "alias": str(raw_device.get("alias") or friendly_name).strip(),
        "ieee_address": ieee_address,
        "model_id": model_id,
        "vendor": vendor,
        "description": str(definition.get("description") or "").strip() or None,
        "device_type": str(raw_device.get("type") or raw_device.get("interview_state") or "").strip() or None,
        "mqtt_base_topic": default_base_topic,
        "mqtt_topic": f"{default_base_topic.strip('/')}/{friendly_name}",
        "sidecar_base_url": sidecar_base_url,
        "capabilities": capabilities,
        "capability_metadata": capability_metadata_from_exposes(exposes),
        "exposes": exposes,
        "definition": definition,
    }


def entity_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    capabilities = list(entry.get("capabilities") or ["connected", "availability", "refresh"])
    return {
        "id": entry["device_id"],
        "name": entry.get("alias") or entry.get("friendly_name") or "Zigbee Device",
        "config_id": entry["config_id"],
        "device_id": entry["device_id"],
        "entity_type": "zigbee_device",
        "capabilities": capabilities,
        "available_commands": available_commands_for(
            capabilities,
            entry.get("exposes") if "exposes" in entry else None,
        ),
        "dashboard": {
            "allowed_widgets": ["tile", "stat", "button"],
            "default_widget": "tile",
        },
        "metadata": {
            "friendly_name": entry.get("friendly_name"),
            "ieee_address": entry.get("ieee_address"),
            "model_id": entry.get("model_id"),
            "vendor": entry.get("vendor"),
            "mqtt_topic": entry.get("mqtt_topic"),
            "capability_metadata": entry.get("capability_metadata") or {},
            "exposes": entry.get("exposes") or [],
        },
    }


def _normalize_expose(expose: dict[str, Any], property_name: str) -> dict[str, Any]:
    capability = PROPERTY_CAPABILITY_MAP.get(property_name)
    return {
        "property": property_name,
        "name": str(expose.get("name") or property_name).strip(),
        "type": str(expose.get("type") or "").strip() or None,
        "unit": expose.get("unit"),
        "min": expose.get("value_min", expose.get("min")),
        "max": expose.get("value_max", expose.get("max")),
        "values": expose.get("values") if isinstance(expose.get("values"), list) else None,
        "access": _normalize_access(expose.get("access")),
        "endpoint": expose.get("endpoint"),
        "description": expose.get("description"),
        "value_on": expose.get("value_on"),
        "value_off": expose.get("value_off"),
        "value_toggle": expose.get("value_toggle"),
        "capability": capability,
    }


def _normalize_access(access: Any) -> dict[str, bool]:
    if isinstance(access, dict):
        return {
            "published": bool(access.get("published") or access.get("read")),
            "set": bool(access.get("set") or access.get("write")),
            "get": bool(access.get("get")),
        }
    if access is None:
        return {"published": True, "set": False, "get": True}
    try:
        value = int(access)
    except (TypeError, ValueError):
        return {"published": True, "set": False, "get": True}
    return {
        "published": bool(value & 1),
        "set": bool(value & 2),
        "get": bool(value & 4),
    }


def _iter_exposes(exposes: Any):
    if not isinstance(exposes, list):
        return
    for expose in exposes:
        if not isinstance(expose, dict):
            continue
        yield expose
        features = expose.get("features")
        if isinstance(features, list):
            for feature in features:
                if isinstance(feature, dict):
                    yield feature


def _format_label(command: str) -> str:
    return command.replace("_", " ").title()
