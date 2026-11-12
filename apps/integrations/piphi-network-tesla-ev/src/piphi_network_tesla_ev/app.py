from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_config_apply_response,
    build_config_remove_response,
    build_local_event_record,
    create_runtime_starter,
    schedule_telemetry_delivery,
)
from piphi_runtime_kit_python.fastapi import (
    dispatch_automation_action_from_fastapi,
    sync_runtime_auth_from_fastapi_payload,
    sync_runtime_auth_from_fastapi_request,
)

from .tesla import (
    FLEET_API_BASE_URLS,
    TeslaClient,
    normalize_summary_state,
    normalize_vehicle_data_state,
    resolve_fleet_api_base_url,
    telemetry_metrics,
)


INTEGRATION_ID = "piphi-network-tesla-ev"
INTEGRATION_NAME = "PiPhi Network Tesla EV"
INTEGRATION_VERSION = "0.2.0"
PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_ROOT.parent
MANIFEST_PATH = (
    PACKAGE_ROOT / "manifest.json"
    if (PACKAGE_ROOT / "manifest.json").exists()
    else SOURCE_ROOT / "manifest.json"
)
BEHAVIORS_PATH = (
    PACKAGE_ROOT / "behaviors.json"
    if (PACKAGE_ROOT / "behaviors.json").exists()
    else SOURCE_ROOT / "behaviors.json"
)
LEDGER_PATH = Path(
    os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "/.piphinetwork/automation-actions.sqlite3")
)

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
automation_registry = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(LEDGER_PATH)
)

SUPPORTED_COMMANDS = {"refresh", "wake_up"}
COMMAND_ALIASES = {
    "tesla.refresh": "refresh",
    "refresh_readings": "refresh",
}
SUPPORTED_CAPABILITIES = {
    "action.refresh",
    "action.wake_up",
    "device.refresh",
    "tesla.refresh",
    "tesla.vehicle_state",
    "tesla.wake",
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _payload_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    config_id = (
        _string(payload.get("configId"))
        or _string(payload.get("config_id"))
        or _string(payload.get("id"))
        or _string(payload.get("vin"))
        or ""
    )
    region = _string(payload.get("region")) or "na"
    if region not in {"na", "eu", "cn"}:
        region = "na"
    return {
        **payload,
        "id": config_id,
        "configId": config_id,
        "config_id": config_id,
        "containerId": _string(payload.get("containerId")) or _string(payload.get("container_id")),
        "integrationId": _string(payload.get("integrationId")) or _string(payload.get("integration_id")),
        "vin": _string(payload.get("vin")) or "",
        "access_token": _string(payload.get("access_token")) or "",
        "region": region,
        "vehicle_name": _string(payload.get("vehicle_name")),
        "include_location": payload.get("include_location") if isinstance(payload.get("include_location"), bool) else True,
        "base_url": _string(payload.get("base_url")),
    }


def _client(config: dict[str, Any]) -> TeslaClient:
    return TeslaClient(
        access_token=str(config["access_token"]),
        region=str(config.get("region") or "na"),
        base_url=config.get("base_url"),
    )


def append_event(
    event_type: str,
    *,
    config_id: str | None = None,
    device_id: str | None = None,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        source=INTEGRATION_ID,
        severity=severity,
        device={"config_id": config_id, "device_id": device_id},
        payload=payload or {},
    )
    registry.append_event(event)
    return event


def _entry(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_id": config["configId"],
        "configId": config["configId"],
        "device_id": state["deviceId"],
        "deviceId": state["deviceId"],
        "vin": config["vin"],
        "display_name": state["displayName"],
        "region": state["region"],
        "base_url": state["baseUrl"],
        "container_id": config.get("containerId"),
        "integration_id": config.get("integrationId") or INTEGRATION_ID,
        "config": config,
        "latest_state": state,
        "last_updated": _now(),
    }


async def deliver_telemetry(entry: dict[str, Any], state: dict[str, Any]) -> None:
    metrics, units = telemetry_metrics(state)
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units=units,
    )


async def refresh_entry(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise RuntimeError(f"Unknown Tesla config: {config_id}")
    config = entry["config"]
    client = _client(config)
    summary = await client.vehicle_summary(str(config["vin"]))
    state = normalize_summary_state(config, summary)
    if summary.get("state") == "online":
        state = normalize_vehicle_data_state(
            config,
            summary,
            await client.vehicle_data(str(config["vin"])),
        )
    updated = {**entry, "display_name": state["displayName"], "latest_state": state, "last_updated": _now()}
    registry.set(config_id, updated)
    registry.update_state(config_id, state, device_id=state["deviceId"])
    append_event(
        "tesla.vehicle.refreshed",
        config_id=config_id,
        device_id=state["deviceId"],
        payload={"vin": state["vin"], "vehicle_state": state["vehicleState"], "source": state["source"]},
    )
    try:
        await deliver_telemetry(updated, state)
    except Exception as exc:
        state = {**state, "lastError": str(exc)}
        updated = {**updated, "latest_state": state}
        registry.set(config_id, updated)
        registry.update_state(config_id, state, device_id=state["deviceId"])
        append_event(
            "tesla.telemetry.delivery_failed",
            config_id=config_id,
            device_id=state["deviceId"],
            severity="warning",
            payload={"message": str(exc)},
        )
    return registry.get(config_id) or updated


async def refresh_all_state() -> None:
    for config_id in registry.ids():
        await refresh_entry(config_id)


starter.state.provide(refresh_all_state, source=INTEGRATION_ID)


async def apply_config(config: dict[str, Any]) -> dict[str, Any]:
    if not config["vin"]:
        raise ValueError("Missing required vin")
    if not config["access_token"]:
        raise ValueError("Missing required access_token")
    summary = await _client(config).vehicle_summary(str(config["vin"]))
    state = normalize_summary_state(config, summary)
    entry = _entry(config, state)
    registry.set(config["configId"], entry)
    registry.update_state(config["configId"], state, device_id=state["deviceId"])
    append_event(
        "tesla.config.applied",
        config_id=config["configId"],
        device_id=state["deviceId"],
        payload={"vin": state["vin"], "vehicle_name": state["displayName"], "region": state["region"]},
    )
    try:
        await refresh_entry(config["configId"])
    except Exception as exc:
        degraded = {**state, "lastError": str(exc)}
        registry.set(config["configId"], {**entry, "latest_state": degraded})
        registry.update_state(config["configId"], degraded, device_id=state["deviceId"])
        append_event(
            "tesla.refresh.degraded",
            config_id=config["configId"],
            device_id=state["deviceId"],
            severity="warning",
            payload={"message": str(exc)},
        )
    return registry.get(config["configId"]) or entry


def remove_config(config_id: str) -> bool:
    removed = registry.remove(config_id)
    if removed:
        append_event(
            "tesla.config.removed",
            config_id=config_id,
            device_id=removed.get("device_id"),
            payload={"vin": removed.get("vin")},
        )
    return removed is not None


def resolve_config_id(payload: dict[str, Any]) -> str:
    target = _payload_dict(payload.get("target"))
    config_id = (
        _string(payload.get("configId"))
        or _string(payload.get("config_id"))
        or _string(target.get("config_id"))
    )
    if config_id:
        return config_id
    primary = registry.primary_entry()
    if primary:
        return str(primary["config_id"])
    raise RuntimeError("No Tesla config is active")


def validate_capabilities(payload: dict[str, Any]) -> None:
    requested = [payload.get("capability")]
    requirements = payload.get("capability_requirements") or payload.get("capabilityRequirements")
    if isinstance(requirements, list):
        requested.extend(requirements)
    unsupported = [str(item) for item in requested if item and str(item) not in SUPPORTED_CAPABILITIES]
    if unsupported:
        raise ValueError(f"Unsupported capability: {unsupported[0]}")


async def execute_action(action: AutomationActionRequest) -> AutomationActionResult:
    extras = action.model_extra or {}
    payload = {**extras, "config_id": action.config_id, "device_id": action.device_id}
    try:
        config_id = resolve_config_id(payload)
        entry = registry.get(config_id)
        if entry is None:
            raise RuntimeError(f"Unknown Tesla config: {config_id}")
        if action.command == "refresh":
            refreshed = await refresh_entry(config_id)
            state = refreshed["latest_state"]
        elif action.command == "wake_up":
            summary = await _client(entry["config"]).wake(str(entry["vin"]))
            state = {
                **normalize_summary_state(entry["config"], summary),
                "lastCommandAt": _now(),
            }
            registry.set(config_id, {**entry, "latest_state": state, "last_updated": _now()})
            registry.update_state(config_id, state, device_id=entry["device_id"])
            append_event(
                "tesla.vehicle.woken",
                config_id=config_id,
                device_id=entry["device_id"],
                payload={"vin": entry["vin"], "vehicle_state": state["vehicleState"]},
            )
        else:
            raise RuntimeError(f"Unsupported command: {action.command}")
    except Exception as exc:
        return AutomationActionResult.failure(
            str(exc), retryable=True, metadata={"status_code": 503}
        )
    target = extras.get("target") if isinstance(extras.get("target"), dict) else {}
    return AutomationActionResult.success(
        {
            "ok": True,
            "command": action.command,
            "contract_version": extras.get("contract_version"),
            "configId": config_id,
            "target": target,
            "params": action.args,
            "state": state,
        }
    )


for _registered_command in sorted(SUPPORTED_COMMANDS):
    automation_registry.action(_registered_command)(execute_action)


def create_app() -> FastAPI:
    application = FastAPI(title=INTEGRATION_NAME, version=INTEGRATION_VERSION)

    @application.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"ok": False, "reason": str(exc)})

    @application.get("/health")
    async def health() -> Any:
        return starter.health_response(
            metadata={"active_configs": len(registry.ids())}
        )

    @application.get("/diagnostics")
    async def diagnostics() -> Any:
        return starter.diagnostics_response(
            diagnostics={
                "active_config_ids": registry.ids(),
                "recent_event_count": len(registry.recent_events),
                "configured_vehicles": [
                    entry.get("vin") for entry in registry.entries.values()
                ],
            }
        )

    @application.get("/manifest.json")
    async def manifest() -> dict[str, Any]:
        return _manifest()

    @application.get("/behaviors.json")
    async def behaviors() -> Any:
        return json.loads(BEHAVIORS_PATH.read_text(encoding="utf-8"))

    @application.get("/ui-config")
    @application.get("/ui")
    async def ui() -> dict[str, Any]:
        manifest_payload = _manifest()
        return {
            "schema": manifest_payload["config"]["schema"],
            "uiSchema": {
                "access_token": {"ui:widget": "password"},
                "base_url": {"ui:placeholder": FLEET_API_BASE_URLS["na"]},
            },
        }

    async def discover_payload(access_token: str, region: str, base_url: str | None) -> dict[str, Any]:
        vehicles = await TeslaClient(access_token, region, base_url).list_vehicles()
        return {
            "devices": [
                {
                    "id": item["vin"],
                    "deviceId": item["vin"],
                    "vin": item["vin"],
                    "display_name": item.get("display_name") or item["vin"],
                    "state": item.get("state") or "unknown",
                    "region": region,
                    "inputs": {"access_token": access_token, "region": region, "base_url": base_url},
                    "suggested_config": {"vin": item["vin"], "region": region},
                }
                for item in vehicles
            ]
        }

    @application.get("/discover")
    @application.get("/discovery")
    async def discover_get(access_token: str = "", region: str = "na", base_url: str | None = None) -> Any:
        if not access_token.strip():
            raise ValueError("Missing access_token for discovery")
        return await discover_payload(access_token, region if region in {"na", "eu", "cn"} else "na", base_url)

    @application.post("/discover")
    @application.post("/discovery")
    async def discover_post(payload: dict[str, Any], request: Request) -> Any:
        sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
        inputs = _payload_dict(payload.get("inputs")) or payload
        access_token = _string(inputs.get("access_token"))
        if not access_token:
            raise ValueError("Missing access_token for discovery")
        region = _string(inputs.get("region")) or "na"
        return await discover_payload(access_token, region if region in {"na", "eu", "cn"} else "na", _string(inputs.get("base_url")))

    @application.post("/config")
    async def configure(payload: dict[str, Any], request: Request) -> Any:
        sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
        config = normalize_config(payload)
        entry = await apply_config(config)
        return build_config_apply_response(
            config_id=config["configId"],
            container_id=config.get("containerId"),
            metadata={
                "vin": entry["vin"],
                "vehicle_name": entry["display_name"],
                "region": entry["region"],
                "base_url": entry["base_url"],
            },
        )

    @application.post("/configs/sync")
    @application.post("/config/sync")
    async def sync_configs(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
        active = set(registry.ids())
        applied: list[str] = []
        for raw in payload.get("configs") if isinstance(payload.get("configs"), list) else []:
            if not isinstance(raw, dict):
                continue
            config = normalize_config(raw)
            if not config["vin"] or not config["access_token"]:
                continue
            await apply_config(config)
            applied.append(config["configId"])
            active.discard(config["configId"])
        removed = [config_id for config_id in active if remove_config(config_id)]
        return {
            "ok": True,
            "generation": payload.get("generation") if isinstance(payload.get("generation"), int) else None,
            "applied_config_ids": applied,
            "removed_config_ids": removed,
            "skipped_config_ids": [],
        }

    @application.post("/deconfigure")
    async def deconfigure(payload: dict[str, Any]) -> Any:
        config_id = _string(payload.get("configId")) or _string(payload.get("config_id"))
        if not config_id:
            raise ValueError("Missing configId")
        return build_config_remove_response(config_id=config_id, removed=remove_config(config_id))

    @application.post("/deconfigure/{config_id}")
    async def deconfigure_path(config_id: str) -> Any:
        return build_config_remove_response(config_id=config_id, removed=remove_config(config_id))

    @application.get("/state")
    async def state(
        refresh: bool = Query(default=False),
        refresh_request_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            state_payload = await starter.state.response(
                refresh=refresh,
                refresh_request_id=refresh_request_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            **state_payload,
            "summary": {"activeConfigCount": len(registry.ids()), "recentEventCount": len(registry.recent_events)},
            "entries": dict(registry.entries),
            "stateSnapshots": dict(registry.state_snapshots),
        }

    @application.get("/events")
    async def events() -> dict[str, Any]:
        return {"events": list(registry.recent_events)}

    @application.get("/entities")
    async def entities() -> dict[str, Any]:
        manifest_payload = _manifest()
        values = []
        for config_id in registry.ids():
            entry = registry.get(config_id)
            if not entry:
                continue
            capabilities = [
                key for key, value in manifest_payload["capabilities"].items()
                if value.get("kind") == "sensor"
                and (entry["latest_state"].get("includeLocation") or key not in {"latitude", "longitude", "heading_degrees"})
            ]
            values.append(
                {
                    "id": entry["device_id"],
                    "name": entry["display_name"],
                    "configId": config_id,
                    "deviceId": entry["device_id"],
                    "deviceType": "vehicle",
                    "deviceClass": "electric_vehicle",
                    "entityType": "sensor",
                    "capabilities": capabilities,
                    "dashboard": {"allowedWidgets": ["tile", "stat", "sensor-card", "status-list"], "defaultWidget": "tile", "recommendedWidgets": ["tile", "stat", "sensor-card"]},
                    "metadata": {"vin": entry["vin"], "region": entry["region"], "vehicle_state": entry["latest_state"].get("vehicleState"), "include_location": entry["latest_state"].get("includeLocation")},
                    "available_commands": [{"id": "refresh", "label": "Refresh"}, {"id": "wake_up", "label": "Wake Up"}],
                }
            )
        return {"entities": values, "capabilities": manifest_payload["capabilities"], "commands": manifest_payload["commands"]}

    @application.post("/command")
    async def command(payload: dict[str, Any], request: Request) -> Any:
        sync_runtime_auth_from_fastapi_request(runtime, request)
        raw = _string(payload.get("command"))
        command_name = COMMAND_ALIASES.get(raw or "", raw or "")
        if not command_name:
            raise ValueError("Missing command")
        if command_name not in SUPPORTED_COMMANDS:
            raise ValueError(f"Unsupported command: {command_name}")
        validate_capabilities(payload)
        config_id = resolve_config_id(payload)
        entry = registry.get(config_id)
        params = payload.get("params") or payload.get("args") or {}
        result = await dispatch_automation_action_from_fastapi(
            automation_registry,
            request,
            {
                **payload,
                "command": command_name,
                "config_id": config_id,
                "device_id": payload.get("device_id") or (entry or {}).get("device_id"),
                "args": params if isinstance(params, dict) else {},
            },
        )
        if not result.ok:
            raise HTTPException(status_code=int(result.metadata.get("status_code") or 503), detail=result.error)
        return {**result.result, "replayed": result.replayed}

    @application.exception_handler(Exception)
    async def runtime_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "runtime_command_failed", "reason": str(exc), "message": str(exc)},
        )

    return application


app = create_app()
