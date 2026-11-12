from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import FALLBACK_ENTITY, FIREWALL_CAPABILITIES
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    runtime_entities: list[dict[str, Any]] = []
    for entry in registry.entries.values():
        device_id = str(entry["device_id"])
        config_id = str(entry["config_id"])
        state = entry.get("latest_state") or {}
        runtime_entities.append(
            {
                "id": device_id,
                "name": entry.get("alias") or entry.get("host") or "pfSense Firewall",
                "config_id": config_id,
                "device_id": device_id,
                "device_type": "firewall",
                "device_class": "network_gateway",
                "entity_type": "network_gateway",
                "capabilities": FIREWALL_CAPABILITIES,
                "available_commands": _available_commands(entry),
                "dashboard": {
                    "allowed_widgets": [
                        "status-list",
                        "gauge",
                        "line-chart",
                        "stat",
                        "button",
                        "external-widget",
                    ],
                    "default_widget": "status-list",
                },
            }
        )
        runtime_entities.extend(
            _interface_entity(device_id, config_id, item)
            for item in state.get("interfaces", [])
        )
        runtime_entities.extend(
            _gateway_entity(device_id, config_id, item)
            for item in state.get("gateways", [])
        )
        runtime_entities.extend(
            _vpn_entity(device_id, config_id, item)
            for item in state.get("vpn_tunnels", [])
        )
        runtime_entities.extend(
            _client_entity(device_id, config_id, item)
            for item in state.get("clients", [])
        )
        runtime_entities.extend(
            _certificate_entity(device_id, config_id, item)
            for item in state.get("certificates", [])
        )
        runtime_entities.extend(
            _carp_entity(device_id, config_id, item)
            for item in state.get("carp_vips", [])
        )
    return {
        "entities": runtime_entities or [FALLBACK_ENTITY],
        "capabilities": capabilities,
        "commands": commands,
    }


def _available_commands(entry: dict[str, Any]) -> list[dict[str, str]]:
    connection = entry.get("connection") or {}
    available = [{"id": "refresh", "label": "Refresh", "kind": "action"}]
    if connection.get("diagnostic_ping_enabled"):
        available.append(
            {"id": "diagnostic_ping", "label": "Diagnostic ping", "kind": "action"}
        )
    if connection.get("service_restart_enabled"):
        available.append(
            {"id": "restart_service", "label": "Restart service", "kind": "action"}
        )
    if connection.get("service_start_enabled"):
        available.append(
            {"id": "start_service", "label": "Start service", "kind": "action"}
        )
    if connection.get("wake_on_lan_enabled"):
        available.append(
            {"id": "wake_on_lan", "label": "Wake device", "kind": "action"}
        )
    return available


def _interface_entity(
    firewall_id: str, config_id: str, interface: dict[str, Any]
) -> dict[str, Any]:
    name = str(interface["name"])
    return {
        "id": f"{firewall_id}:interface:{name}",
        "name": str(interface.get("description") or name),
        "config_id": config_id,
        "device_id": f"{firewall_id}:interface:{name}",
        "parent_device_id": firewall_id,
        "device_type": "network_interface",
        "device_class": "network_interface",
        "entity_type": "network_interface",
        "capabilities": [
            "interface_up",
            "bytes_received",
            "bytes_sent",
            "errors_in",
            "errors_out",
            "receive_rate_bps",
            "transmit_rate_bps",
        ],
        "available_commands": [],
        "dashboard": {
            "allowed_widgets": ["status-list", "line-chart", "stat"],
            "default_widget": "status-list",
        },
    }


def _vpn_entity(
    firewall_id: str, config_id: str, tunnel: dict[str, Any]
) -> dict[str, Any]:
    name = str(tunnel["name"])
    protocol = str(tunnel["protocol"])
    device_id = f"{firewall_id}:vpn:{protocol}:{name}"
    return {
        "id": device_id,
        "name": str(tunnel.get("description") or name),
        "config_id": config_id,
        "device_id": device_id,
        "parent_device_id": firewall_id,
        "device_type": "vpn_tunnel",
        "device_class": protocol,
        "entity_type": "vpn_tunnel",
        "capabilities": [
            "vpn_connected",
            "vpn_bytes_received",
            "vpn_bytes_sent",
            "vpn_peer_count",
        ],
        "available_commands": [],
        "dashboard": {
            "allowed_widgets": ["status-list", "line-chart", "stat"],
            "default_widget": "status-list",
        },
    }


def _gateway_entity(
    firewall_id: str, config_id: str, gateway: dict[str, Any]
) -> dict[str, Any]:
    name = str(gateway["name"])
    return {
        "id": f"{firewall_id}:gateway:{name}",
        "name": name,
        "config_id": config_id,
        "device_id": f"{firewall_id}:gateway:{name}",
        "parent_device_id": firewall_id,
        "device_type": "network_gateway",
        "device_class": "wan_gateway",
        "entity_type": "network_gateway",
        "capabilities": [
            "gateway_online",
            "gateway_latency_ms",
            "gateway_loss_percent",
        ],
        "available_commands": [],
        "dashboard": {
            "allowed_widgets": ["status-list", "gauge", "line-chart", "stat"],
            "default_widget": "status-list",
        },
    }


def _client_entity(
    firewall_id: str, config_id: str, client: dict[str, Any]
) -> dict[str, Any]:
    device_id = f"{firewall_id}:client:{client['id']}"
    return {
        "id": device_id,
        "name": client["name"],
        "config_id": config_id,
        "device_id": device_id,
        "parent_device_id": firewall_id,
        "device_type": "network_client",
        "device_class": "network_client",
        "entity_type": "network_client",
        "capabilities": ["client_online"],
        "available_commands": [],
        "dashboard": {
            "allowed_widgets": ["status-list", "tile"],
            "default_widget": "status-list",
        },
    }


def _certificate_entity(
    firewall_id: str, config_id: str, certificate: dict[str, Any]
) -> dict[str, Any]:
    device_id = f"{firewall_id}:certificate:{certificate['id']}"
    return {
        "id": device_id,
        "name": certificate["name"],
        "config_id": config_id,
        "device_id": device_id,
        "parent_device_id": firewall_id,
        "device_type": "certificate",
        "device_class": "certificate",
        "entity_type": "certificate",
        "capabilities": ["certificate_days_remaining"],
        "available_commands": [],
        "dashboard": {
            "allowed_widgets": ["stat", "line-chart"],
            "default_widget": "stat",
        },
    }


def _carp_entity(
    firewall_id: str, config_id: str, vip: dict[str, Any]
) -> dict[str, Any]:
    device_id = f"{firewall_id}:carp:{vip['id']}"
    return {
        "id": device_id,
        "name": vip["name"],
        "config_id": config_id,
        "device_id": device_id,
        "parent_device_id": firewall_id,
        "device_type": "carp_virtual_ip",
        "device_class": "high_availability",
        "entity_type": "carp_virtual_ip",
        "capabilities": ["carp_primary"],
        "available_commands": [],
        "dashboard": {
            "allowed_widgets": ["status-list", "tile"],
            "default_widget": "status-list",
        },
    }
