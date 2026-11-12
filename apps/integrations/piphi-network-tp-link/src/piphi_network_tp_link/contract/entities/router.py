from fastapi import APIRouter
from piphi_runtime_kit_python import build_entities_response

from piphi_network_tp_link.lib.manifest import load_manifest
from piphi_network_tp_link.lib.store import registry

router = APIRouter(tags=["entities"])


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value or "").strip() for value in values if str(value or "").strip()]


def _normalize_device_class(raw_device_type: object, capabilities: list[str]) -> str:
    token = str(raw_device_type or "").strip().lower()
    if "bulb" in token or "light" in token or any(
        capability in capabilities
        for capability in ["brightness", "color_temperature", "color"]
    ):
        return "light"
    if "dimmer" in token:
        return "dimmer"
    if "strip" in token:
        return "strip"
    if "plug" in token or "socket" in token or "switch" in token or "energy" in capabilities:
        return "plug"
    return token or "device"


def _entity_type(device_class: str, capabilities: list[str]) -> str:
    if any(capability in capabilities for capability in ["brightness", "color_temperature", "color"]):
        return "light"
    if "switch" in capabilities:
        return "switch"
    if any(capability in capabilities for capability in ["power", "energy_power", "energy_today", "energy_this_month"]):
        return "energy"
    return "device"


def _dashboard_hints(device_class: str, capabilities: list[str]) -> dict[str, object]:
    has_energy = any(
        capability in capabilities
        for capability in [
            "power",
            "energy_power",
            "energy_today",
            "energy_this_month",
        ]
    )
    if device_class in {"light", "dimmer", "strip"}:
        return {
            "allowed_widgets": ["device-control", "smart-plug", "energy-monitor"],
            "default_widget": "device-control",
            "recommended_widgets": [
                "device-control",
                *(["smart-plug", "energy-monitor"] if has_energy else []),
            ],
        }
    if "switch" in capabilities:
        return {
            "allowed_widgets": ["device-control", "smart-plug", "energy-monitor"],
            "default_widget": "smart-plug" if has_energy else "device-control",
            "recommended_widgets": (
                ["smart-plug", "device-control", "energy-monitor"]
                if has_energy
                else ["device-control"]
            ),
        }
    if any(capability in capabilities for capability in ["temperature", "humidity"]):
        return {
            "allowed_widgets": ["environment-monitor"],
            "default_widget": "environment-monitor",
            "recommended_widgets": ["environment-monitor"],
        }
    return {
        "allowed_widgets": ["energy-monitor"],
        "default_widget": "energy-monitor",
        "recommended_widgets": ["energy-monitor"],
    }


def _available_commands(device_class: str, capabilities: list[str]) -> list[dict[str, object]]:
    commands: list[dict[str, object]] = []

    def add(
        command_name: str,
        *,
        label: str | None = None,
        kind: str | None = None,
        description: str | None = None,
        args_schema: dict[str, object] | None = None,
    ) -> None:
        if any(command.get("id") == command_name for command in commands):
            return
        commands.append(
            {
                "id": command_name,
                "label": label or command_name.replace("_", " ").title(),
                "kind": kind,
                "description": description,
                "args_schema": args_schema or {},
            }
        )

    capability_set = set(capabilities)

    if device_class in {"light", "dimmer", "strip"} or "switch" in capability_set:
        add("toggle", label="Toggle", kind="primary", description="Toggle the device power state.")
        add("turn_on", label="Turn On", kind="primary", description="Turn the device on.")
        add("turn_off", label="Turn Off", kind="secondary", description="Turn the device off.")

    if "brightness" in capability_set:
        add(
            "set_brightness",
            label="Set Brightness",
            kind="adjust",
            description="Adjust brightness from 0 to 100 percent.",
            args_schema={
                "brightness": {
                    "type": "number",
                    "label": "Brightness",
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "unit": "%",
                    "required": True,
                }
            },
        )

    if "color_temperature" in capability_set:
        add(
            "set_color_temperature",
            label="Set Color Temperature",
            kind="adjust",
            description="Adjust white temperature in kelvin where supported.",
            args_schema={
                "kelvin": {
                    "type": "number",
                    "label": "Kelvin",
                    "min": 2200,
                    "max": 6500,
                    "step": 100,
                    "unit": "K",
                    "required": True,
                }
            },
        )

    if "color" in capability_set:
        add(
            "set_hue_saturation",
            label="Set Color",
            kind="adjust",
            description="Adjust hue and saturation where supported.",
            args_schema={
                "hue": {
                    "type": "number",
                    "label": "Hue",
                    "min": 0,
                    "max": 360,
                    "step": 1,
                    "required": True,
                },
                "saturation": {
                    "type": "number",
                    "label": "Saturation",
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "unit": "%",
                    "required": True,
                },
            },
        )

    if any(
        capability in capability_set
        for capability in ["power", "energy_power", "energy_today", "energy_this_month"]
    ):
        add(
            "read_energy",
            label="Refresh Energy",
            kind="secondary",
            description="Request the latest energy metrics from the device.",
        )

    add("refresh", label="Refresh", kind="secondary", description="Refresh the latest device state.")
    return commands


@router.get("/entities")
async def get_entities() -> dict:
    manifest = load_manifest()
    entities: list[dict] = []

    for device_id in registry.ids():
        entry = registry.get(device_id) or {}
        latest_state = entry.get("latest_state") if isinstance(entry.get("latest_state"), dict) else {}
        capabilities = _string_list(latest_state.get("capabilities"))
        if not capabilities:
            continue

        device_class = _normalize_device_class(latest_state.get("device_type"), capabilities)
        name = (
            str(entry.get("alias") or "").strip()
            or str(latest_state.get("alias") or "").strip()
            or str(latest_state.get("name") or "").strip()
            or str(device_id)
        )
        entities.append(
            {
                "id": str(entry.get("device_id") or device_id),
                "name": name,
                "config_id": str(entry.get("config_id") or "").strip() or None,
                "device_id": str(entry.get("device_id") or device_id),
                "device_type": str(latest_state.get("device_type") or "").strip() or None,
                "device_class": device_class,
                "entity_type": _entity_type(device_class, capabilities),
                "capabilities": capabilities,
                "available_commands": _available_commands(device_class, capabilities),
                "dashboard": _dashboard_hints(device_class, capabilities),
                "alias": str(entry.get("alias") or "").strip() or None,
                "host": str(entry.get("host") or "").strip() or None,
                "latest_state": latest_state,
                "metadata": {
                    "model": latest_state.get("model"),
                    "host": entry.get("host"),
                    "physical_device_id": entry.get("physical_device_id"),
                },
            }
        )

    return build_entities_response(
        entities=entities,
        capabilities=manifest.get("capabilities", {}),
        commands=manifest.get("commands", {}),
    ).model_dump(exclude_none=True)
