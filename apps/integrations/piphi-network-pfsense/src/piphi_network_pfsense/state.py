from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    assert_behaviors_contract,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .contract import CAPABILITIES, COMMANDS
from .pfsense_client import PfSenseError
from .schemas import DeviceConfig
from .service import PfSenseRuntimeService
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
config_sync = starter.config_sync
automations = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(
        os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "./data/automation-actions.sqlite3")
    )
)

capabilities = CAPABILITIES
commands = COMMANDS
pfsense_service = PfSenseRuntimeService(
    registry=registry,
    runtime=runtime,
    telemetry=telemetry,
    event_client=starter.event_client,
    record_event=registry.append_event,
)
_packaged_behaviors = Path(__file__).with_name("behaviors.json")
_source_behaviors = Path(__file__).resolve().parents[1] / "behaviors.json"
BEHAVIORS = json.loads(
    (
        _packaged_behaviors if _packaged_behaviors.exists() else _source_behaviors
    ).read_text()
)
automations.event(
    "device.state_changed",
    label="pfSense state changed",
    data_schema={
        "capabilities": {"type": "array"},
        "changed_metrics": {"type": "array"},
    },
)
for _event_type, _label in {
    "network.gateway.online": "Gateway came online",
    "network.gateway.offline": "Gateway went offline",
    "network.interface.up": "Interface came up",
    "network.interface.down": "Interface went down",
    "network.service.recovered": "Service recovered",
    "network.service.stopped": "Service stopped",
    "network.client.discovered": "Network client discovered",
    "network.client.online": "Network client came online",
    "network.client.offline": "Network client went offline",
    "network.certificate.expiring": "Certificate is expiring",
    "network.certificate.expired": "Certificate expired",
    "network.ha.role_changed": "CARP role changed",
    "network.security.firewall_log": "Firewall security log received",
    "network.security.auth_log": "Authentication log received",
    "network.client.dhcp_event": "DHCP log event received",
    "network.system.log_event": "System log event received",
}.items():
    automations.event(
        _event_type,
        label=_label,
        data_schema={
            "name": {"type": "string"},
            "status": {"type": ["string", "null"]},
        },
    )


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "connection": {
            "base_url": config.base_url,
            "simulation_mode": config.simulation_mode,
            "verify_tls": config.verify_tls,
            "custom_ca": bool(config.ca_bundle_path),
            "collect_dhcp_leases": config.collect_dhcp_leases,
            "collect_vpn_status": config.collect_vpn_status,
            "collect_client_inventory": config.collect_client_inventory,
            "collect_security_logs": config.collect_security_logs,
            "collect_certificates": config.collect_certificates,
            "collect_ha_status": config.collect_ha_status,
            "diagnostic_ping_enabled": config.enable_diagnostic_ping,
            "service_restart_enabled": config.enable_service_restart,
            "service_start_enabled": config.enable_service_start,
            "wake_on_lan_enabled": config.enable_wake_on_lan,
        },
    }


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity="info",
    )
    registry.append_event(event)
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    config_id = str(entry["config_id"])
    previous = registry.get(config_id)
    registry.set(config_id, entry)
    try:
        await pfsense_service.configure(config, entry)
    except Exception:
        if previous is None:
            registry.remove(config_id)
        else:
            registry.set(config_id, previous)
        raise
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias, "read_only": True},
    )


async def remove_config(config_id: str) -> bool:
    await pfsense_service.remove(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


@automations.action(
    "refresh",
    label="Refresh read-only status from pfSense.",
    result_schema={"state": {"type": "object"}},
)
async def refresh_automation(request: AutomationActionRequest) -> dict[str, Any]:
    target_value = getattr(request, "target", None)
    target = target_value if isinstance(target_value, dict) else {}
    config_id = str(request.config_id or target.get("config_id") or "")
    if not config_id:
        primary = registry.primary_entry()
        if primary is None:
            raise HTTPException(status_code=409, detail="pfSense is not configured")
        config_id = str(primary["config_id"])
    entry = get_entry_or_404(config_id)
    state = await pfsense_service.refresh(config_id)
    event = append_runtime_event(
        "runtime.command.received",
        entry,
        {"command": "refresh", "read_only": True},
    )
    return {
        "event": event,
        "command": "refresh",
        "config_id": config_id,
        "device_id": str(entry["device_id"]),
        "state": state,
    }


@automations.action(
    "diagnostic_ping",
    label="Ping an allow-listed target from pfSense.",
    parameter_schema={
        "host": {"type": "string"},
        "count": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    result_schema={
        "host": {"type": "string"},
        "result_code": {"type": ["integer", "null"]},
        "output": {"type": ["string", "null"]},
    },
)
async def diagnostic_ping_automation(
    request: AutomationActionRequest,
) -> dict[str, Any]:
    config_id, entry = _action_context(request)
    host = str(request.args.get("host") or "").strip()
    if not host:
        raise HTTPException(status_code=422, detail="diagnostic_ping requires host")
    raw_count = request.args.get("count", 3)
    if isinstance(raw_count, bool):
        raise HTTPException(status_code=422, detail="ping count must be an integer")
    try:
        count = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="ping count must be an integer"
        ) from exc

    append_runtime_event(
        "runtime.command.requested",
        entry,
        {"command": "diagnostic_ping", "host": host, "count": count},
    )
    try:
        result = await pfsense_service.diagnostic_ping(
            config_id, host=host, count=count
        )
    except (HTTPException, PfSenseError) as exc:
        append_runtime_event(
            "runtime.command.failed",
            entry,
            {"command": "diagnostic_ping", "host": host, "error": str(exc)},
        )
        raise
    append_runtime_event(
        "runtime.command.succeeded",
        entry,
        {"command": "diagnostic_ping", "host": host},
    )
    return {
        "command": "diagnostic_ping",
        "config_id": config_id,
        "device_id": str(entry["device_id"]),
        "host": host,
        "result_code": result.get("result_code"),
        "output": result.get("output"),
    }


@automations.action(
    "restart_service",
    label="Restart an allow-listed pfSense service.",
    parameter_schema={"service": {"type": "string"}},
    result_schema={
        "service": {"type": "string"},
        "running": {"type": ["boolean", "null"]},
    },
)
async def restart_service_automation(
    request: AutomationActionRequest,
) -> dict[str, Any]:
    config_id, entry = _action_context(request)
    service_name = str(request.args.get("service") or "").strip()
    if not service_name:
        raise HTTPException(status_code=422, detail="restart_service requires service")

    append_runtime_event(
        "runtime.command.requested",
        entry,
        {"command": "restart_service", "service": service_name},
    )
    try:
        result = await pfsense_service.restart_service(
            config_id, service_name=service_name
        )
    except (HTTPException, PfSenseError) as exc:
        append_runtime_event(
            "runtime.command.failed",
            entry,
            {"command": "restart_service", "service": service_name, "error": str(exc)},
        )
        raise
    append_runtime_event(
        "runtime.command.succeeded",
        entry,
        {"command": "restart_service", "service": service_name},
    )
    return {
        "command": "restart_service",
        "config_id": config_id,
        "device_id": str(entry["device_id"]),
        "service": service_name,
        "running": result.get("status"),
    }


@automations.action(
    "start_service",
    label="Start an allow-listed pfSense service.",
    parameter_schema={"service": {"type": "string"}},
    result_schema={
        "service": {"type": "string"},
        "running": {"type": ["boolean", "null"]},
    },
)
async def start_service_automation(request: AutomationActionRequest) -> dict[str, Any]:
    config_id, entry = _action_context(request)
    service_name = str(request.args.get("service") or "").strip()
    if not service_name:
        raise HTTPException(status_code=422, detail="start_service requires service")
    append_runtime_event(
        "runtime.command.requested",
        entry,
        {"command": "start_service", "service": service_name},
    )
    try:
        result = await pfsense_service.start_service(
            config_id, service_name=service_name
        )
    except (HTTPException, PfSenseError) as exc:
        append_runtime_event(
            "runtime.command.failed",
            entry,
            {"command": "start_service", "service": service_name, "error": str(exc)},
        )
        raise
    append_runtime_event(
        "runtime.command.succeeded",
        entry,
        {"command": "start_service", "service": service_name},
    )
    return {
        "command": "start_service",
        "config_id": config_id,
        "device_id": str(entry["device_id"]),
        "service": service_name,
        "running": result.get("status"),
    }


@automations.action(
    "wake_on_lan",
    label="Wake a preconfigured LAN target.",
    parameter_schema={"target_id": {"type": "string"}},
    result_schema={
        "target_id": {"type": "string"},
        "target_label": {"type": "string"},
    },
)
async def wake_on_lan_automation(request: AutomationActionRequest) -> dict[str, Any]:
    config_id, entry = _action_context(request)
    target_id = str(request.args.get("target_id") or "").strip()
    if not target_id:
        raise HTTPException(status_code=422, detail="wake_on_lan requires target_id")
    append_runtime_event(
        "runtime.command.requested",
        entry,
        {"command": "wake_on_lan", "target_id": target_id},
    )
    try:
        result = await pfsense_service.wake_on_lan(config_id, target_id=target_id)
    except (HTTPException, PfSenseError) as exc:
        append_runtime_event(
            "runtime.command.failed",
            entry,
            {"command": "wake_on_lan", "target_id": target_id, "error": str(exc)},
        )
        raise
    append_runtime_event(
        "runtime.command.succeeded",
        entry,
        {"command": "wake_on_lan", "target_id": result["target_id"]},
    )
    return {
        "command": "wake_on_lan",
        "config_id": config_id,
        "device_id": str(entry["device_id"]),
        "target_id": result["target_id"],
        "target_label": result["target_label"],
    }


def _action_context(
    request: AutomationActionRequest,
) -> tuple[str, dict[str, Any]]:
    target_value = getattr(request, "target", None)
    target = target_value if isinstance(target_value, dict) else {}
    config_id = str(request.config_id or target.get("config_id") or "")
    if not config_id:
        primary = registry.primary_entry()
        if primary is None:
            raise HTTPException(status_code=409, detail="pfSense is not configured")
        config_id = str(primary["config_id"])
    return config_id, get_entry_or_404(config_id)


assert_behaviors_contract(BEHAVIORS, automations)


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await pfsense_service.refresh(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
