from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
import httpx
from pydantic import BaseModel, ConfigDict

from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationRegistry,
    IntegrationCommandRequest,
    IntegrationDiscoveryRequest,
    IntegrationDiscoveryResponse,
    IntegrationEventListResponse,
    RuntimeConfig,
    RuntimeConfigApplyResponse,
    RuntimeConfigRemoveResponse,
    RuntimeConfigSnapshot,
    RuntimeConfigSyncResponse,
    RuntimeDiagnosticsResponse,
    RuntimeHealthResponse,
    SQLiteAutomationIdempotencyStore,
    MqttBrokerConfig,
    MqttJsonClient,
    build_source_topic_root,
    build_config_apply_response,
    build_discovery_response,
    build_event_list_response,
    build_local_event_record,
    create_tracked_task,
    create_runtime_starter,
    resolve_core_base_url,
    runtime_lifespan,
    schedule_event_delivery,
    schedule_telemetry_delivery,
    validate_typed_configs,
)
from piphi_runtime_kit_python.fastapi import (
    dispatch_automation_action_from_fastapi,
    sync_runtime_auth_from_fastapi_payload,
)

from .profiles import (
    PROFILE_DEFINITIONS,
    build_entities,
    extract_metrics,
    format_capability_name,
    infer_profile_id,
    list_profiles,
    metric_units,
    normalize_profile_id,
)


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _resolve_discovery_cache_path() -> Path | None:
    value = os.getenv("RTL433_DISCOVERY_CACHE_PATH")
    if value is not None and not value.strip():
        return None
    return Path(value or "/tmp/piphi-network-433mhz-discovery.json")


INTEGRATION_ID = "piphi-network-433mhz"
INTEGRATION_NAME = "PiPhi Network 433MHz Devices"
INTEGRATION_VERSION = "0.2.0"
RTL433_BRIDGE_SERVICE_ID = "piphi.service.rtl433-bridge"
RTL433_BRIDGE_URL_ENV = "PIPHI_SERVICE_RTL433_BRIDGE_RUNTIME_URL"
MAX_DISCOVERY_CACHE = 200
DISCOVERY_WAIT_SECONDS = max(
    0.0,
    min(_env_float("RTL433_DISCOVERY_WAIT_SECONDS", 8.0), 18.0),
)
DISCOVERY_CACHE_PATH = _resolve_discovery_cache_path()
MQTT_SOURCE_ENABLED = _env_flag("RTL433_MQTT_ENABLED", False)
MQTT_BROKER_HOSTNAME = os.getenv("MQTT_HOSTNAME", "127.0.0.1")
MQTT_BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_BROKER_USERNAME = os.getenv("MQTT_USERNAME") or None
MQTT_BROKER_PASSWORD = os.getenv("MQTT_PASSWORD") or None
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID") or f"{INTEGRATION_ID}-subscriber"
MQTT_QOS = int(os.getenv("MQTT_QOS", "0"))
MQTT_TOPIC_ROOT = os.getenv("MQTT_TOPIC_ROOT", build_source_topic_root("rtl433"))
MQTT_PACKET_TOPIC = f"{MQTT_TOPIC_ROOT.rstrip('/')}/packets"
MQTT_RETRY_DELAY_SECONDS = float(os.getenv("MQTT_RETRY_DELAY_SECONDS", "5"))
MAX_PACKET_BYTES = max(1024, min(int(os.getenv("RTL433_MAX_PACKET_BYTES", "65536")), 1_048_576))
DEDUP_WINDOW_SECONDS = max(0.0, min(_env_float("RTL433_DEDUP_WINDOW_SECONDS", 2.0), 60.0))
DEVICE_EXPIRY_SECONDS = max(30.0, min(_env_float("RTL433_DEVICE_EXPIRY_SECONDS", 610.0), 86_400.0))
DISCOVERY_EVENT_INTERVAL_SECONDS = max(
    1.0, min(_env_float("RTL433_DISCOVERY_EVENT_INTERVAL_SECONDS", 60.0), 3600.0)
)

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
    core_base_url=resolve_core_base_url("http://127.0.0.1:31419"),
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
event_client = starter.event_client
config_sync = starter.config_sync
recent_seen_devices: OrderedDict[str, dict[str, Any]] = OrderedDict()
discovery_waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
packet_fingerprints: OrderedDict[str, float] = OrderedDict()
last_discovery_event_at: dict[str, float] = {}
ingress_counters = {
    "accepted": 0,
    "duplicates": 0,
    "invalid": 0,
    "unidentified": 0,
    "discovery_events_suppressed": 0,
}
_last_cache_persist_monotonic = 0.0
_automation_ledger_path = Path(
    os.getenv(
        "PIPHI_AUTOMATION_LEDGER_PATH",
        "/.piphinetwork/automation-actions.sqlite3",
    )
)
automation_registry = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(_automation_ledger_path)
)


async def _clear_discovery_cache_action(
    action_request: AutomationActionRequest,
) -> dict[str, Any]:
    count = len(recent_seen_devices)
    recent_seen_devices.clear()
    persist_discovery_cache(force=True)
    return {
        "status": "ok",
        "command": action_request.command,
        "result": {"cleared_discovery_records": count},
    }


automation_registry.action("clear_discovery_cache")(_clear_discovery_cache_action)


class Rtl433DeviceConfig(RuntimeConfig):
    profile: str = "auto"
    model: str
    station_id: str
    channel: str | None = None
    alias: str | None = None


class Rtl433Packet(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    id: str | int | None = None
    channel: str | int | None = None


def _optional_config_attr(config: RuntimeConfig, name: str) -> Any:
    return getattr(config, name, None)


def build_device_key(model: str | None, station_id: Any, channel: Any = None) -> str:
    model_part = str(model or "unknown")
    station_part = str(station_id or "unknown")
    channel_part = str(channel) if channel not in (None, "") else "na"
    return f"{model_part}::{station_part}::{channel_part}"


def extract_station_id(packet: dict[str, Any]) -> str:
    for key in ("id", "device_id", "device", "sid", "unit"):
        value = packet.get(key)
        if value not in (None, ""):
            return str(value)
    return "unknown"


def extract_channel(packet: dict[str, Any]) -> str | None:
    for key in ("channel", "subtype"):
        value = packet.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def make_registry_entry(config: Rtl433DeviceConfig) -> dict[str, Any]:
    profile_id = normalize_profile_id(config.profile)
    device_key = build_device_key(config.model, config.station_id, config.channel)
    return {
        "config_id": _optional_config_attr(config, "config_id") or config.id,
        "device_id": device_key,
        "container_id": _optional_config_attr(config, "container_id"),
        "integration_id": _optional_config_attr(config, "integration_id") or INTEGRATION_ID,
        "profile": profile_id,
        "model": config.model,
        "station_id": config.station_id,
        "channel": config.channel,
        "alias": config.alias,
    }


def append_runtime_event(
    *,
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> None:
    registry.append_event(
        build_local_event_record(
            event_type=event_type,
            device=device,
            payload=payload,
            source=INTEGRATION_ID,
            severity=severity,
        )
    )


def emit_leak_transition_event(
    *,
    entry: dict[str, Any],
    previous_metrics: dict[str, Any],
    current_metrics: dict[str, Any],
    profile_id: str,
    source_transport: str,
) -> None:
    # Generic RF fields are not safety-qualified. Canonical leak events remain
    # disabled until an immutable model/decoder qualification matrix exists.
    return
    if "leak_detected" not in previous_metrics or "leak_detected" not in current_metrics:
        return
    previous_value = previous_metrics.get("leak_detected")
    current_value = current_metrics.get("leak_detected")
    if (
        previous_value == current_value
        or not isinstance(previous_value, bool)
        or not isinstance(current_value, bool)
    ):
        return

    event_type = (
        "rtl433.safety.leak.detected"
        if current_value
        else "rtl433.safety.leak.cleared"
    )
    event_payload = {
        "capability": "leak_detected",
        "previous_value": previous_value,
        "current_value": current_value,
        "profile": profile_id,
        "transport": source_transport,
    }
    append_runtime_event(
        event_type=event_type,
        device=entry,
        payload=event_payload,
        severity="warning",
    )
    schedule_event_delivery(
        process_state=runtime.process_state,
        event_client=event_client,
        auth_context=runtime.auth,
        event_type=event_type,
        device=entry,
        payload=event_payload,
        source=INTEGRATION_ID,
        severity="warning",
    )


async def apply_config(config: Rtl433DeviceConfig) -> None:
    entry = make_registry_entry(config)
    registry.set(config.id, entry)
    registry.update_state(
        config.id,
        {
            "profile": entry["profile"],
            "model": entry["model"],
            "station_id": entry["station_id"],
            "channel": entry["channel"],
            "alias": entry["alias"],
            "last_packet_at": None,
            "last_packet_monotonic": None,
            "available": False,
        },
    )
    append_runtime_event(
        event_type="rtl433.config.applied",
        device=entry,
        payload={
            "profile": entry["profile"],
            "model": entry["model"],
            "station_id": entry["station_id"],
            "channel": entry["channel"],
        },
    )


async def remove_config(config_id: str) -> bool:
    removed = registry.remove(config_id)
    if removed is None:
        return False
    append_runtime_event(
        event_type="rtl433.config.removed",
        device=removed,
        payload={"config_id": config_id},
    )
    return True


def remember_discovered_device(packet: dict[str, Any]) -> dict[str, Any]:
    profile_id = infer_profile_id(packet)
    model = str(packet.get("model") or "").strip()
    station_id = extract_station_id(packet)
    if not model or station_id == "unknown":
        raise ValueError("A stable rtl_433 model and station identifier are required for discovery.")
    channel = extract_channel(packet)
    device_key = build_device_key(model, station_id, channel)
    metrics = extract_metrics(packet, profile_id)
    record = {
        "id": device_key,
        "device_id": device_key,
        "profile": profile_id,
        "profile_name": PROFILE_DEFINITIONS[profile_id].name,
        "model": model,
        "station_id": station_id,
        "channel": channel or "",
        "alias": model,
        "last_seen_at": now_iso(),
        "preview_metrics": metrics,
    }
    recent_seen_devices[device_key] = record
    recent_seen_devices.move_to_end(device_key)
    while len(recent_seen_devices) > MAX_DISCOVERY_CACHE:
        recent_seen_devices.popitem(last=False)
    persist_discovery_cache()
    notify_discovery_waiters()
    return record


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_discovery_cache(*, force: bool = False) -> None:
    global _last_cache_persist_monotonic
    if not DISCOVERY_CACHE_PATH:
        return
    now = time.monotonic()
    if not force and _last_cache_persist_monotonic and now - _last_cache_persist_monotonic < 1.0:
        return

    payload = {
        "version": 1,
        "updated_at": now_iso(),
        "devices": list(recent_seen_devices.values()),
    }
    try:
        DISCOVERY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = DISCOVERY_CACHE_PATH.with_suffix(f"{DISCOVERY_CACHE_PATH.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp_path.replace(DISCOVERY_CACHE_PATH)
        _last_cache_persist_monotonic = now
    except OSError as exc:
        print(f"rtl433_discovery_cache_persist_failed path={DISCOVERY_CACHE_PATH} error={exc}")


def load_discovery_cache() -> None:
    if not DISCOVERY_CACHE_PATH:
        return

    if not DISCOVERY_CACHE_PATH.exists():
        return

    try:
        payload = json.loads(DISCOVERY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"rtl433_discovery_cache_load_failed path={DISCOVERY_CACHE_PATH} error={exc}")
        return

    devices = payload.get("devices") if isinstance(payload, dict) else None
    if not isinstance(devices, list):
        return

    recent_seen_devices.clear()
    for item in devices[-MAX_DISCOVERY_CACHE:]:
        if not isinstance(item, dict):
            continue
        device_id = str(item.get("device_id") or item.get("id") or "").strip()
        if not device_id:
            continue
        if item.get("channel") is None:
            item["channel"] = ""
        recent_seen_devices[device_id] = item
    print(f"rtl433_discovery_cache_loaded count={len(recent_seen_devices)} path={DISCOVERY_CACHE_PATH}")


def notify_discovery_waiters() -> None:
    for loop, event in list(discovery_waiters):
        if loop.is_closed():
            discovery_waiters.discard((loop, event))
            continue
        loop.call_soon_threadsafe(event.set)


def filter_recent_devices(requested_profile: Any = None) -> list[dict[str, Any]]:
    devices = list(recent_seen_devices.values())
    if requested_profile:
        profile = str(requested_profile)
        devices = [device for device in devices if device.get("profile") == profile]
    return devices


async def wait_for_discovery_devices(requested_profile: Any = None) -> list[dict[str, Any]]:
    devices = filter_recent_devices(requested_profile)
    if devices or DISCOVERY_WAIT_SECONDS <= 0:
        return devices

    deadline = time.monotonic() + DISCOVERY_WAIT_SECONDS
    loop = asyncio.get_running_loop()
    event = asyncio.Event()
    waiter = (loop, event)
    discovery_waiters.add(waiter)

    try:
        while time.monotonic() < deadline:
            devices = filter_recent_devices(requested_profile)
            if devices:
                return devices

            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break

            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except TimeoutError:
                break
    finally:
        discovery_waiters.discard(waiter)

    return filter_recent_devices(requested_profile)


async def startup_sync(_runtime_context, _client) -> None:
    load_discovery_cache()

    result = await starter.rehydrate_configs(
        client=_client,
        apply_snapshot=apply_runtime_config_snapshot,
        config_model=Rtl433DeviceConfig,
        snapshot_model=RuntimeConfigSnapshot,
    )

    if result.snapshot_applied:
        print(
            "rtl433_startup_rehydrate_complete "
            f"loaded={result.snapshot_config_count} "
            f"generation={result.snapshot_generation} "
            "source=snapshot"
        )

    if result.core_applied:
        print(
            "rtl433_startup_rehydrate_complete "
            f"loaded={result.core_config_count} "
            f"generation={result.core_generation} "
            "source=core"
        )
    elif result.core_error:
        print(f"rtl433_startup_core_rehydrate_failed error={result.core_error}")
    elif result.missing_runtime_auth:
        print("rtl433_startup_missing_runtime_credentials standalone_mode=true")
    elif result.core_attempted:
        print("rtl433_startup_rehydrate_no_configs")

    if not MQTT_SOURCE_ENABLED:
        return
    mqtt_client = MqttJsonClient(
        MqttBrokerConfig(
            hostname=MQTT_BROKER_HOSTNAME,
            port=MQTT_BROKER_PORT,
            username=MQTT_BROKER_USERNAME,
            password=MQTT_BROKER_PASSWORD,
            client_id=MQTT_CLIENT_ID,
            qos=MQTT_QOS,
        )
    )
    create_tracked_task(
        mqtt_client.run_subscription_forever(
            topics=[MQTT_PACKET_TOPIC],
            handler=handle_mqtt_packet,
            retry_delay_seconds=MQTT_RETRY_DELAY_SECONDS,
        ),
        process_state=runtime.process_state,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> RuntimeHealthResponse:
    stale_count = refresh_availability()
    return starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "recent_discovery_count": len(recent_seen_devices),
            "supported_profile_count": len(PROFILE_DEFINITIONS),
            "mqtt_source_enabled": MQTT_SOURCE_ENABLED,
            "stale_config_count": stale_count,
            "ingress": dict(ingress_counters),
        }
    )


@app.get("/diagnostics")
async def diagnostics() -> RuntimeDiagnosticsResponse:
    stale_count = refresh_availability()
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "recent_discovery_count": len(recent_seen_devices),
            "supported_profiles": list_profiles(),
            "mqtt_packet_topic": MQTT_PACKET_TOPIC if MQTT_SOURCE_ENABLED else None,
            "stale_config_count": stale_count,
            "ingress": dict(ingress_counters),
            "packet_limits": {
                "max_bytes": MAX_PACKET_BYTES,
                "dedup_window_seconds": DEDUP_WINDOW_SECONDS,
                "device_expiry_seconds": DEVICE_EXPIRY_SECONDS,
            },
        }
    )


@app.get("/ui-config")
async def ui_config() -> dict[str, Any]:
    profile_ids = list(PROFILE_DEFINITIONS.keys())
    profile_names = [profile.name for profile in PROFILE_DEFINITIONS.values()]

    return {
        "schema": {
            "title": "Wireless Sensor Setup",
            "description": (
                "Review the 433 MHz sensor PiPhi heard. Discovery fills most of this in, "
                "and you can leave the channel blank if you do not know it."
            ),
            "type": "object",
            "required": ["model", "station_id"],
            "properties": {
                "profile": {
                    "type": "string",
                    "title": "Device type",
                    "description": (
                        "Auto-detect is recommended. PiPhi will record safe decoded readings "
                        "from each radio packet."
                    ),
                    "enum": profile_ids,
                    "default": "auto",
                },
                "model": {
                    "type": "string",
                    "title": "Sensor model",
                    "description": (
                        "Usually filled from the radio packet. Leave it as discovered unless "
                        "you know it is wrong."
                    ),
                },
                "station_id": {
                    "type": "string",
                    "title": "Sensor ID",
                    "description": "The ID broadcast by the sensor. PiPhi uses it to recognize this device later.",
                },
                "channel": {
                    "type": "string",
                    "title": "Channel (optional)",
                    "description": (
                        "Leave blank if you do not know it. This is only needed when several "
                        "sensors share the same model and ID."
                    ),
                    "default": "",
                },
                "alias": {
                    "type": "string",
                    "title": "Display name",
                    "description": "A friendly name shown in dashboards and device lists.",
                    "default": "",
                },
            },
        },
        "uiSchema": {
            "ui:options": {
                "translations": {
                    "submit": "Save Device",
                },
            },
            "profile": {
                "ui:components": {
                    "stringField": "enumField",
                },
                "ui:options": {
                    "enumNames": profile_names,
                    "flowbite3Select": {
                        "placeholder": "Auto-detect",
                    },
                },
            },
            "model": {
                "ui:options": {
                    "flowbite3Text": {
                        "placeholder": "Fineoffset-WH0290",
                    },
                },
            },
            "station_id": {
                "ui:options": {
                    "flowbite3Text": {
                        "placeholder": "62",
                    },
                },
            },
            "channel": {
                "ui:options": {
                    "flowbite3Text": {
                        "placeholder": "Leave blank if unknown",
                    },
                },
            },
            "alias": {
                "ui:options": {
                    "flowbite3Text": {
                        "placeholder": "Backyard weather sensor",
                    },
                },
            },
        },
        "profiles": list_profiles(),
    }


@app.post("/discover", response_model=IntegrationDiscoveryResponse)
async def discover(
    payload: IntegrationDiscoveryRequest | None = None,
) -> IntegrationDiscoveryResponse:
    requested_profile = None
    discovery_inputs: dict[str, Any] = {}
    if payload and payload.inputs:
        discovery_inputs = dict(payload.inputs)
        requested_profile = payload.inputs.get("profile")

    await configure_discovery_receiver(discovery_inputs)
    devices = await wait_for_discovery_devices(requested_profile)
    return build_discovery_response(devices)


async def configure_discovery_receiver(inputs: dict[str, Any]) -> None:
    settings = {
        "frequency": _clean_discovery_input(inputs.get("radio_frequency")),
        "rtlsdr_device": _clean_discovery_input(inputs.get("rtlsdr_device")),
    }
    settings = {key: value for key, value in settings.items() if value is not None}
    if not settings:
        return

    bridge_url = resolve_rtl433_bridge_url()
    if bridge_url is None:
        raise HTTPException(
            status_code=503,
            detail="The rtl_433 radio service is not ready. Start the connection and try again.",
        )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            headers = {}
            service_token = resolve_rtl433_bridge_token()
            if service_token:
                headers["X-PiPhi-Service-Token"] = service_token
            response = await client.post(
                f"{bridge_url.rstrip('/')}/radio/config", json=settings, headers=headers
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = "The radio service rejected those receiver settings."
        try:
            response_detail = exc.response.json().get("detail")
            if response_detail:
                detail = str(response_detail)
        except (ValueError, AttributeError):
            pass
        raise HTTPException(status_code=422, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="The rtl_433 radio service could not be reached. Check the connection and try again.",
        ) from exc


def resolve_rtl433_bridge_url() -> str | None:
    direct_url = str(os.getenv(RTL433_BRIDGE_URL_ENV) or "").strip()
    if direct_url:
        return direct_url

    try:
        bindings = json.loads(os.getenv("PIPHI_SERVICE_BINDINGS", "{}"))
    except json.JSONDecodeError:
        return None
    binding = bindings.get(RTL433_BRIDGE_SERVICE_ID) if isinstance(bindings, dict) else None
    if not isinstance(binding, dict) or binding.get("status") != "available":
        return None
    url = str(binding.get("runtime_url") or binding.get("url") or "").strip()
    return url or None


def resolve_rtl433_bridge_token() -> str | None:
    direct_token = str(os.getenv("PIPHI_SERVICE_RTL433_BRIDGE_AUTH_TOKEN") or "").strip()
    if direct_token:
        return direct_token
    try:
        bindings = json.loads(os.getenv("PIPHI_SERVICE_BINDINGS", "{}"))
    except json.JSONDecodeError:
        return None
    binding = bindings.get(RTL433_BRIDGE_SERVICE_ID) if isinstance(bindings, dict) else None
    if not isinstance(binding, dict):
        return None
    token = str(binding.get("auth_token") or binding.get("token") or "").strip()
    return token or None


def _clean_discovery_input(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


@app.post("/config")
async def config(
    payload: Rtl433DeviceConfig,
    request: Request,
) -> RuntimeConfigApplyResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    await apply_config(payload)
    device_key = build_device_key(payload.model, payload.station_id, payload.channel)
    return build_config_apply_response(
        config_id=_optional_config_attr(payload, "config_id") or payload.id,
        container_id=_optional_config_attr(payload, "container_id"),
        metadata={
            "profile": normalize_profile_id(payload.profile),
            "device_id": device_key,
            "device_key": device_key,
        },
    )


async def apply_runtime_config_snapshot(
    snapshot: RuntimeConfigSnapshot,
) -> RuntimeConfigSyncResponse:
    typed_configs = validate_typed_configs(
        [
            config.model_dump() if isinstance(config, RuntimeConfig) else config
            for config in snapshot.configs
        ],
        Rtl433DeviceConfig,
    )
    return await config_sync.apply_snapshot(
        snapshot=snapshot.model_copy(update={"configs": typed_configs}),
        active_config_ids=registry.ids(),
        apply_config=apply_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


@app.post("/config/sync")
async def sync_config(
    snapshot: RuntimeConfigSnapshot,
    request: Request,
) -> RuntimeConfigSyncResponse:
    runtime.auth.sync_from_headers(request.headers, payload_container_id=snapshot.container_id)
    return await apply_runtime_config_snapshot(snapshot)


@app.post("/deconfigure/{config_id}")
async def deconfigure(config_id: str) -> RuntimeConfigRemoveResponse:
    removed = await remove_config(config_id)
    return RuntimeConfigRemoveResponse(
        config_id=config_id,
        removed=removed,
        metadata={"remaining_configs": registry.ids()},
    )


@app.get("/entities")
async def entities() -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for entry in registry.entries.values():
        device_name = entry.get("alias") or entry["device_id"]
        payload.extend(
            build_entities(
                device_name=device_name,
                device_key=str(entry["device_id"]),
                profile_id=str(entry.get("profile") or "generic_sensor"),
                metric_names=list(entry.get("observed_metrics") or []),
            )
        )
    return payload


@app.get("/state")
async def state(
    refresh: bool = Query(default=False),
    refresh_request_id: str | None = Query(default=None),
) -> dict[str, Any]:
    refresh_availability()
    try:
        state_payload = await starter.state.response(
            refresh=refresh,
            refresh_request_id=refresh_request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **state_payload,
        "summary": {
            "active_config_count": len(registry.ids()),
            "recent_event_count": len(registry.recent_events),
            "recent_discovery_count": len(recent_seen_devices),
        },
        # ``entries`` is part of this integration's existing public API.
        # Only the refresh receipt is new; do not rename or reshape it.
        "entries": registry.entries,
        "state_snapshots": registry.state_snapshots,
        "recent_seen_devices": list(recent_seen_devices.values())[-25:],
    }


@app.get("/events", response_model=IntegrationEventListResponse)
async def list_events(limit: int = 50) -> IntegrationEventListResponse:
    return build_event_list_response(registry.recent_events[-limit:])


@app.post("/command")
async def command(
    payload: IntegrationCommandRequest,
    request: Request,
) -> dict[str, Any]:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    if payload.command == "clear_discovery_cache":
        result = await dispatch_automation_action_from_fastapi(
            automation_registry,
            request,
            payload,
        )
        if not result.ok:
            return {
                "status": "failed",
                "command": payload.command,
                "result": {"message": result.error},
                "replayed": result.replayed,
            }
        return {**result.result, "replayed": result.replayed}

    return {
        "status": "unsupported",
        "command": payload.command,
        "result": {"message": f"Unsupported command: {payload.command}"},
    }


@app.post("/ingest/rtl433")
async def ingest_rtl433(packet: Rtl433Packet, request: Request) -> dict[str, Any]:
    _authorize_ingest(request)
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdecimal() and int(content_length) > MAX_PACKET_BYTES:
        raise HTTPException(status_code=413, detail="rtl_433 packet exceeds the configured size limit")
    runtime.auth.sync_from_headers(request.headers)
    payload = packet.model_dump(exclude_none=True)
    if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > MAX_PACKET_BYTES:
        raise HTTPException(status_code=413, detail="rtl_433 packet exceeds the configured size limit")
    return await process_rtl433_packet(payload, source_transport="http")


async def handle_mqtt_packet(_topic: str, envelope: dict[str, Any]) -> None:
    packet = envelope.get("packet")
    if not isinstance(packet, dict):
        return
    await process_rtl433_packet(packet, source_transport="mqtt")


async def process_rtl433_packet(
    payload: dict[str, Any],
    *,
    source_transport: str,
) -> dict[str, Any]:
    if not _bounded_json(payload):
        ingress_counters["invalid"] += 1
        raise HTTPException(status_code=422, detail="rtl_433 packet contains unsupported or excessive values")
    fingerprint = _packet_fingerprint(payload)
    if _is_duplicate_fingerprint(fingerprint):
        ingress_counters["duplicates"] += 1
        return {"status": "duplicate", "transport": source_transport, "matched_configs": 0, "metric_names": []}
    try:
        discovered = remember_discovered_device(payload)
    except ValueError as exc:
        ingress_counters["unidentified"] += 1
        return {
            "status": "ignored",
            "reason": str(exc),
            "transport": source_transport,
            "matched_configs": 0,
            "metric_names": [],
        }
    ingress_counters["accepted"] += 1

    matched_configs = 0
    for config_id, entry in registry.entries.items():
        if str(entry.get("device_id")) != discovered["device_id"]:
            continue

        matched_configs += 1
        configured_profile_id = normalize_profile_id(str(entry.get("profile") or "auto"))
        inferred_profile_id = str(discovered.get("profile") or "generic_sensor")
        profile_id = (
            inferred_profile_id
            if configured_profile_id in {"auto", "generic_sensor"} and inferred_profile_id != "generic_sensor"
            else configured_profile_id
        )
        if profile_id != entry.get("profile"):
            entry["profile"] = profile_id
        metrics = extract_metrics(payload, profile_id)
        current_snapshot = registry.state_snapshots.get(config_id)
        current_state = (
            current_snapshot.get("state")
            if isinstance(current_snapshot, dict)
            else {}
        )
        previous_metrics = (
            current_state.get("last_metrics")
            if isinstance(current_state, dict)
            else {}
        )
        if not isinstance(previous_metrics, dict):
            previous_metrics = {}
        merged_metrics = {**previous_metrics, **metrics}
        entry["observed_metrics"] = sorted(
            set(entry.get("observed_metrics") or []) | set(metrics)
        )
        registry.update_state(
            config_id,
            {
                "last_packet_at": now_iso(),
                "last_packet_monotonic": time.monotonic(),
                "available": True,
                "model": discovered["model"],
                "station_id": discovered["station_id"],
                "channel": discovered["channel"],
                "profile": profile_id,
                "last_metrics": merged_metrics,
                "observed_metrics": entry["observed_metrics"],
            },
        )

        if metrics:
            schedule_telemetry_delivery(
                process_state=runtime.process_state,
                telemetry_client=telemetry,
                auth_context=runtime.auth,
                config_id=str(entry["config_id"]),
                device_id=str(entry["device_id"]),
                container_id=entry.get("container_id"),
                metrics=metrics,
                units=metric_units(profile_id, list(metrics.keys())),
            )

        emit_leak_transition_event(
            entry=entry,
            previous_metrics=previous_metrics,
            current_metrics=metrics,
            profile_id=profile_id,
            source_transport=source_transport,
        )

        append_runtime_event(
            event_type="rtl433.packet.matched",
            device=entry,
            payload={
                "transport": source_transport,
                "profile": profile_id,
                "metrics": metrics,
                "model": discovered["model"],
                "station_id": discovered["station_id"],
            },
        )

    if matched_configs == 0:
        now = time.monotonic()
        last_event_at = last_discovery_event_at.get(discovered["device_id"], 0.0)
        if now - last_event_at >= DISCOVERY_EVENT_INTERVAL_SECONDS:
            last_discovery_event_at[discovered["device_id"]] = now
            append_runtime_event(
            event_type="rtl433.packet.discovered",
            device={
                "config_id": discovered["id"],
                "device_id": discovered["device_id"],
                "integration_id": INTEGRATION_ID,
                "container_id": runtime.auth.container_id or None,
            },
            payload={
                "transport": source_transport,
                "profile": discovered["profile"],
                "model": discovered["model"],
                "station_id": discovered["station_id"],
                "channel": discovered["channel"],
            },
            )
        else:
            ingress_counters["discovery_events_suppressed"] += 1

    return {
        "status": "ok",
        "transport": source_transport,
        "device_id": discovered["device_id"],
        "profile": discovered["profile"],
        "matched_configs": matched_configs,
        "metric_names": [
            format_capability_name(metric_name)
            for metric_name in extract_metrics(payload, discovered["profile"]).keys()
        ],
    }


def _authorize_ingest(request: Request) -> None:
    expected_token = str(os.getenv("RTL433_INGEST_TOKEN") or "").strip()
    production = str(os.getenv("PIPHI_ENV") or os.getenv("ENVIRONMENT") or "").lower() == "production"
    if not expected_token:
        if production:
            raise HTTPException(status_code=503, detail="rtl_433 ingest authentication is not configured")
        return
    received_token = str(request.headers.get("X-PiPhi-Bridge-Token") or "").strip()
    if not received_token or not secrets.compare_digest(received_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid rtl_433 bridge authentication")


def _packet_fingerprint(payload: dict[str, Any]) -> str:
    stable_payload = {key: value for key, value in payload.items() if key not in {"time", "received_at"}}
    canonical = json.dumps(stable_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_duplicate_fingerprint(fingerprint: str) -> bool:
    if DEDUP_WINDOW_SECONDS <= 0:
        return False
    now = time.monotonic()
    cutoff = now - DEDUP_WINDOW_SECONDS
    while packet_fingerprints:
        _, seen_at = next(iter(packet_fingerprints.items()))
        if seen_at >= cutoff:
            break
        packet_fingerprints.popitem(last=False)
    seen_at = packet_fingerprints.get(fingerprint)
    packet_fingerprints[fingerprint] = now
    packet_fingerprints.move_to_end(fingerprint)
    return seen_at is not None and seen_at >= cutoff


def _bounded_json(value: Any, *, depth: int = 0) -> bool:
    if depth > 5:
        return False
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= 2048
    if isinstance(value, list):
        return len(value) <= 128 and all(_bounded_json(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        return len(value) <= 256 and all(
            isinstance(key, str)
            and len(key) <= 128
            and _bounded_json(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def refresh_availability() -> int:
    now = time.monotonic()
    stale_count = 0
    for config_id in registry.ids():
        snapshot = registry.state_snapshots.get(config_id)
        state = snapshot.get("state") if isinstance(snapshot, dict) else None
        if not isinstance(state, dict):
            continue
        last_packet = state.get("last_packet_monotonic")
        available = isinstance(last_packet, (int, float)) and now - last_packet <= DEVICE_EXPIRY_SECONDS
        if not available:
            stale_count += 1
        if state.get("available") != available:
            registry.update_state(config_id, {**state, "available": available})
    return stale_count
