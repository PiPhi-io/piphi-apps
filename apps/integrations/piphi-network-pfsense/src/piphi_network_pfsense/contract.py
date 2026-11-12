from __future__ import annotations

from typing import Any

ENDPOINTS = {
    "health": "/health",
    "diagnostics": "/diagnostics",
    "discover": "/discover",
    "entities": "/entities",
    "state": "/state",
    "config": "/config",
    "config_sync": "/config/sync",
    "deconfigure": "/deconfigure",
    "ui_config": "/ui-config",
    "events": "/events",
    "command": "/command",
}

REQUIRED_ENDPOINTS = ["health", "entities", "command", "config", "ui_config"]


def _sensor(unit: str | None = None, *widgets: str) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": "sensor"}
    if unit:
        value["unit"] = unit
    if widgets:
        value["dashboard"] = {
            "allowed_widgets": list(widgets),
            "default_widget": widgets[0],
        }
    return value


CAPABILITIES: dict[str, dict[str, Any]] = {
    "connected": _sensor("bool", "tile", "status-list"),
    "api_latency_ms": _sensor("ms", "stat", "line-chart"),
    "cpu_usage_percent": _sensor("%", "gauge", "line-chart", "stat"),
    "memory_usage_percent": _sensor("%", "gauge", "line-chart", "stat"),
    "disk_usage_percent": _sensor("%", "gauge", "line-chart", "stat"),
    "swap_usage_percent": _sensor("%", "gauge", "line-chart", "stat"),
    "mbuf_usage_percent": _sensor("%", "gauge", "line-chart", "stat"),
    "temperature_c": _sensor("C", "stat", "line-chart"),
    "interface_count": _sensor("interfaces", "stat"),
    "interfaces_up": _sensor("interfaces", "stat"),
    "interface_up": _sensor("bool", "tile", "status-list"),
    "bytes_received": _sensor("bytes", "stat", "line-chart"),
    "bytes_sent": _sensor("bytes", "stat", "line-chart"),
    "errors_in": _sensor("errors", "stat", "line-chart"),
    "errors_out": _sensor("errors", "stat", "line-chart"),
    "receive_rate_bps": _sensor("bit/s", "stat", "line-chart"),
    "transmit_rate_bps": _sensor("bit/s", "stat", "line-chart"),
    "gateway_count": _sensor("gateways", "stat"),
    "gateways_online": _sensor("gateways", "stat"),
    "gateways_offline": _sensor("gateways", "stat"),
    "gateway_online": _sensor("bool", "tile", "status-list"),
    "gateway_latency_ms": _sensor("ms", "stat", "line-chart"),
    "gateway_loss_percent": _sensor("%", "gauge", "line-chart"),
    "gateway_max_latency_ms": _sensor("ms", "stat", "line-chart"),
    "gateway_max_loss_percent": _sensor("%", "gauge", "line-chart"),
    "service_count": _sensor("services", "stat"),
    "services_running": _sensor("services", "stat"),
    "services_down": _sensor("services", "stat", "status-list"),
    "dhcp_lease_count": _sensor("leases", "stat"),
    "dhcp_online_lease_count": _sensor("leases", "stat"),
    "vpn_tunnel_count": _sensor("tunnels", "stat"),
    "vpn_tunnels_up": _sensor("tunnels", "stat", "status-list"),
    "openvpn_server_connections": _sensor("connections", "stat"),
    "vpn_connected": _sensor("bool", "tile", "status-list"),
    "vpn_bytes_received": _sensor("bytes", "stat", "line-chart"),
    "vpn_bytes_sent": _sensor("bytes", "stat", "line-chart"),
    "vpn_peer_count": _sensor("peers", "stat"),
    "client_count": _sensor("clients", "stat"),
    "clients_online": _sensor("clients", "stat", "status-list"),
    "clients": _sensor("json"),
    "client_online": _sensor("bool", "tile", "status-list"),
    "certificate_count": _sensor("certificates", "stat"),
    "certificates_expiring": _sensor("certificates", "stat", "status-list"),
    "certificates_expired": _sensor("certificates", "stat", "status-list"),
    "certificate_days_remaining": _sensor("days", "stat", "line-chart"),
    "ha_enabled": _sensor("bool", "tile", "status-list"),
    "ha_maintenance_mode": _sensor("bool", "tile", "status-list"),
    "ha_sync_enabled": _sensor("bool", "tile", "status-list"),
    "carp_vip_count": _sensor("virtual IPs", "stat"),
    "carp_primary_count": _sensor("virtual IPs", "stat"),
    "carp_primary": _sensor("bool", "tile", "status-list"),
    "security_log_count": _sensor("entries", "stat"),
    "refresh": {
        "kind": "action",
        "dashboard": {"allowed_widgets": ["tile"], "default_widget": "tile"},
    },
    "diagnostic_ping": {
        "kind": "action",
        "dashboard": {"allowed_widgets": ["tile"], "default_widget": "tile"},
    },
    "restart_service": {
        "kind": "action",
        "dashboard": {"allowed_widgets": ["tile"], "default_widget": "tile"},
    },
    "start_service": {
        "kind": "action",
        "dashboard": {"allowed_widgets": ["tile"], "default_widget": "tile"},
    },
    "wake_on_lan": {
        "kind": "action",
        "dashboard": {"allowed_widgets": ["tile"], "default_widget": "tile"},
    },
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh read-only status from pfSense.",
        "timeout_ms": 30000,
    },
    "diagnostic_ping": {
        "description": "Ping an allow-listed target from pfSense.",
        "timeout_ms": 30000,
    },
    "restart_service": {
        "description": "Restart an explicitly allow-listed pfSense service.",
        "timeout_ms": 60000,
    },
    "start_service": {
        "description": "Start an explicitly allow-listed pfSense service.",
        "timeout_ms": 60000,
    },
    "wake_on_lan": {
        "description": "Wake a preconfigured LAN target through pfSense.",
        "timeout_ms": 30000,
    },
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "pfSense REST API Setup",
        "type": "object",
        "required": [],
        "properties": {
            "host": {
                "type": "string",
                "title": "pfSense hostname or IP",
                "default": "simulated-pfsense.local",
            },
            "alias": {
                "type": "string",
                "title": "Display name",
                "default": "pfSense Firewall",
            },
            "api_key": {
                "type": "string",
                "title": "REST API key",
                "format": "password",
            },
            "port": {
                "type": "integer",
                "title": "API port",
                "minimum": 1,
                "maximum": 65535,
                "default": 443,
            },
            "scheme": {
                "type": "string",
                "title": "Protocol",
                "enum": ["https", "http"],
                "default": "https",
            },
            "verify_tls": {
                "type": "boolean",
                "title": "Verify TLS certificate",
                "default": True,
            },
            "ca_bundle_path": {"type": "string", "title": "Custom CA bundle path"},
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll interval",
                "minimum": 30,
                "maximum": 3600,
                "default": 60,
            },
            "collect_dhcp_leases": {
                "type": "boolean",
                "title": "Collect DHCP lease counts",
                "default": False,
            },
            "collect_vpn_status": {
                "type": "boolean",
                "title": "Collect VPN status",
                "default": False,
            },
            "collect_client_inventory": {
                "type": "boolean",
                "title": "Collect DHCP and ARP client inventory",
                "default": False,
            },
            "collect_security_logs": {
                "type": "boolean",
                "title": "Collect security and connectivity logs",
                "default": False,
            },
            "collect_certificates": {
                "type": "boolean",
                "title": "Collect certificate expiry metadata",
                "default": False,
            },
            "collect_ha_status": {
                "type": "boolean",
                "title": "Collect CARP and HA status",
                "default": False,
            },
            "enable_diagnostic_ping": {
                "type": "boolean",
                "title": "Enable diagnostic ping action",
                "default": False,
            },
            "allowed_ping_hosts": {
                "type": "array",
                "title": "Allowed ping targets",
                "items": {"type": "string"},
                "default": [],
            },
            "enable_service_restart": {
                "type": "boolean",
                "title": "Enable service restart action",
                "default": False,
            },
            "enable_service_start": {
                "type": "boolean",
                "title": "Enable service start action",
                "default": False,
            },
            "allowed_services": {
                "type": "array",
                "title": "Services allowed to restart",
                "items": {"type": "string"},
                "default": [],
            },
            "enable_wake_on_lan": {
                "type": "boolean",
                "title": "Enable Wake-on-LAN action",
                "default": False,
            },
            "wake_on_lan_targets": {
                "type": "array",
                "title": "Allowed Wake-on-LAN targets",
                "default": [],
                "items": {
                    "type": "object",
                    "required": ["id", "label", "interface", "mac_addr"],
                    "properties": {
                        "id": {"type": "string", "title": "Target ID"},
                        "label": {"type": "string", "title": "Display name"},
                        "interface": {"type": "string", "title": "pfSense interface"},
                        "mac_addr": {"type": "string", "title": "MAC address"},
                    },
                },
            },
            "simulation_mode": {
                "type": "boolean",
                "title": "Use simulated pfSense firewall",
                "default": False,
            },
        },
    },
    "uiSchema": {
        "host": {"placeholder": "pfsense.example.lan"},
        "api_key": {"ui:widget": "password", "placeholder": "pfREST API key"},
        "ca_bundle_path": {"placeholder": "/run/secrets/pfsense-ca.pem"},
        "scheme": {"ui:widget": "select"},
        "allowed_ping_hosts": {"ui:options": {"orderable": False}},
        "allowed_services": {"ui:options": {"orderable": False}},
        "wake_on_lan_targets": {"ui:options": {"orderable": False}},
        "simulation_mode": {
            "ui:help": "Developer mode: use deterministic firewall, gateway, VPN, client, certificate, and HA data without contacting pfSense."
        },
    },
}

FIREWALL_CAPABILITIES = [
    name
    for name in CAPABILITIES
    if name
    not in {
        "interface_up",
        "bytes_received",
        "bytes_sent",
        "errors_in",
        "errors_out",
        "receive_rate_bps",
        "transmit_rate_bps",
        "gateway_online",
        "gateway_latency_ms",
        "gateway_loss_percent",
        "vpn_connected",
        "vpn_bytes_received",
        "vpn_bytes_sent",
        "vpn_peer_count",
        "client_online",
        "certificate_days_remaining",
        "carp_primary",
    }
]

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "pfsense-firewall",
    "name": "pfSense Firewall",
    "device_id": "pfsense-firewall",
    "device_type": "firewall",
    "device_class": "network_gateway",
    "entity_type": "network_gateway",
    "capabilities": FIREWALL_CAPABILITIES,
    "available_commands": [
        {"id": "refresh", "label": "Refresh", "kind": "action"},
        {"id": "diagnostic_ping", "label": "Diagnostic ping", "kind": "action"},
        {"id": "restart_service", "label": "Restart service", "kind": "action"},
        {"id": "start_service", "label": "Start service", "kind": "action"},
        {"id": "wake_on_lan", "label": "Wake device", "kind": "action"},
    ],
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
