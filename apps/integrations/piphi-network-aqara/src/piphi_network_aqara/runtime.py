from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
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
    build_config_apply_response,
    build_config_remove_response,
    build_discovery_response,
    build_event_list_response,
    build_local_event_record,
    create_runtime_starter,
    create_tracked_task,
    resolve_core_base_url,
    schedule_event_delivery,
    schedule_telemetry_delivery,
    validate_typed_configs,
)
from piphi_runtime_kit_python.fastapi import (
    dispatch_automation_action_from_fastapi,
    sync_runtime_auth_from_fastapi_payload,
)
from piphi_runtime_kit_python.runtime.errors import CoreDeliveryError

from .cloud.client import (
    AqaraCloudAuthError,
    AqaraCloudClient,
    AqaraCloudError,
    AqaraCloudRateLimitError,
    AqaraCloudRequestError,
)
from .cloud.models import AqaraAuthTokens, AqaraCloudCredentials, AqaraCloudDevice, AqaraResourceInfo, AqaraResourceValue
from .cloud.registry import capability_for_resource, command_bindings_for_capabilities
from .manifest import load_manifest
from .security import redact_recursive


manifest = load_manifest()
INTEGRATION_ID = str(manifest.get("id") or "aqara-open-api")
INTEGRATION_NAME = str(manifest.get("name") or "Aqara (Open API)")
INTEGRATION_VERSION = str(manifest.get("version") or "0.1.0")
DEFAULT_POLL_INTERVAL_SECONDS = 300
MAX_TRACKED_PUSH_MSG_IDS = 512
logger = logging.getLogger(__name__)

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
    core_base_url=resolve_core_base_url("http://127.0.0.1:31419"),
)


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await _read_and_store(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
runtime = starter.runtime
registry = starter.registry
telemetry_client = starter.telemetry_client
event_client = starter.event_client
config_sync = starter.config_sync
cloud_client = AqaraCloudClient()
router = APIRouter()
AUTOMATION_COMMANDS = frozenset(
    {"close", "open", "refresh", "set_brightness", "set_position", "turn_off", "turn_on"}
)
_automation_ledger_path = Path(
    os.getenv(
        "PIPHI_AUTOMATION_LEDGER_PATH",
        "/.piphinetwork/automation-actions.sqlite3",
    )
)
automation_registry = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(_automation_ledger_path)
)
poll_tasks: dict[str, asyncio.Task[Any]] = {}
poll_status: dict[str, dict[str, Any]] = {}
processed_push_msg_ids: deque[str] = deque()
processed_push_msg_id_set: set[str] = set()
push_dedupe_lock = asyncio.Lock()
push_status: dict[str, Any] = {
    "last_received_at": None,
    "last_processed_at": None,
    "last_duplicate_at": None,
    "last_stale_at": None,
    "last_error": None,
    "last_msg_id": None,
    "last_message_type": None,
    "received_count": 0,
    "processed_count": 0,
    "duplicate_count": 0,
    "stale_count": 0,
}

CAPABILITY_UNITS = {
    "temperature_c": "C",
    "humidity_percent": "%",
    "pressure_hpa": "hPa",
    "battery_percent": "%",
    "illuminance_lux": "lux",
    "co2_ppm": "ppm",
    "voc_ppb": "ppb",
    "pm25_ugm3": "ug/m3",
    "power_w": "W",
    "energy_kwh": "kWh",
    "voltage_v": "V",
    "current_a": "A",
    "frequency_hz": "Hz",
    "brightness_percent": "%",
    "cover_position": "%",
}
BOOLEAN_CAPABILITIES = {
    "motion_detected",
    "presence_detected",
    "person_detected",
    "audio_detected",
    "doorbell_pressed",
    "contact_open",
    "leak_detected",
    "smoke_alarm",
    "gas_alarm",
    "switch_on",
    "locked",
    "privacy_mode",
    "recording_enabled",
    "battery_low",
    "tamper_detected",
    "lock_jammed",
    "connected",
}
DEFAULT_ALLOWED_WIDGETS = ["sensor-card", "stat", "line-chart", "tile"]
ELECTRICAL_CAPABILITIES = {"power_w", "energy_kwh", "voltage_v", "current_a", "frequency_hz", "power_factor"}
CAMERA_WIDGET_CAPABILITIES = {"privacy_mode", "recording_enabled", "person_detected", "audio_detected", "doorbell_pressed"}
CAMERA_EVENT_CAPABILITIES = {"motion_detected", "person_detected", "audio_detected", "doorbell_pressed"}


class AqaraCloudConfig(RuntimeConfig):
    region: str = Field(default="us")
    app_id: str
    key_id: str
    app_key: str
    access_token: str | None = None
    refresh_token: str | None = None
    open_id: str | None = None
    account: str | None = None
    account_type: int = 0
    auth_code: str | None = None
    custom_api_domain: str | None = None
    did: str
    device_name: str | None = None
    device_model: str | None = None
    poll_interval_seconds: int = Field(default=DEFAULT_POLL_INTERVAL_SECONDS, ge=60, le=86400)


class DeconfigurePayload(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


def set_cloud_client(client: AqaraCloudClient) -> None:
    global cloud_client
    cloud_client = client


async def reset_runtime_state() -> None:
    for task in list(poll_tasks.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    poll_tasks.clear()
    poll_status.clear()
    processed_push_msg_ids.clear()
    processed_push_msg_id_set.clear()
    push_status.update(
        {
            "last_received_at": None,
            "last_processed_at": None,
            "last_duplicate_at": None,
            "last_stale_at": None,
            "last_error": None,
            "last_msg_id": None,
            "last_message_type": None,
            "received_count": 0,
            "processed_count": 0,
            "duplicate_count": 0,
            "stale_count": 0,
        }
    )
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime.auth.container_id = ""
    runtime.auth.internal_token = ""
    runtime.process_state.background_tasks.clear()
    runtime.process_state.current_generation = None


async def _resolve_credentials(
    *,
    region: str,
    app_id: str,
    key_id: str,
    app_key: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
    open_id: str | None = None,
    account: str | None = None,
    account_type: int = 0,
    auth_code: str | None = None,
    custom_api_domain: str | None = None,
) -> tuple[AqaraCloudCredentials, AqaraAuthTokens | None]:
    normalized_region = str(region or "").strip().lower()
    normalized_custom_domain = str(custom_api_domain or "").strip() or None
    if normalized_custom_domain:
        raise HTTPException(
            status_code=400,
            detail="custom_api_domain is not supported; Aqara traffic is restricted to the official endpoint for the selected region.",
        )
    if normalized_region not in {"cn", "us", "eu", "kr", "ru", "sg"}:
        raise HTTPException(status_code=400, detail="Unsupported Aqara region. Choose cn, us, eu, kr, ru, or sg.")
    credentials = AqaraCloudCredentials(
        region=normalized_region,
        app_id=str(app_id or "").strip(),
        key_id=str(key_id or "").strip(),
        app_key=str(app_key or "").strip(),
        access_token=str(access_token or "").strip(),
        refresh_token=str(refresh_token or "").strip() or None,
        open_id=str(open_id or "").strip(),
        account=str(account or "").strip() or None,
        account_type=int(account_type or 0),
        custom_api_domain=normalized_custom_domain,
    )
    if not credentials.region or not credentials.app_id or not credentials.key_id or not credentials.app_key:
        raise HTTPException(status_code=400, detail="region, app_id, key_id, and app_key are required.")
    if credentials.access_token and credentials.open_id:
        return credentials, None
    if not credentials.account or not str(auth_code or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Provide access_token plus open_id, or provide account plus auth_code.",
        )
    tokens = await cloud_client.exchange_token(
        credentials,
        account=credentials.account,
        auth_code=str(auth_code or "").strip(),
        account_type=credentials.account_type,
    )
    refreshed = credentials.with_tokens(tokens)
    return refreshed, tokens


def _entry_credentials(entry: dict[str, Any]) -> AqaraCloudCredentials:
    return AqaraCloudCredentials(
        region=str(entry["region"]),
        app_id=str(entry["app_id"]),
        key_id=str(entry["key_id"]),
        app_key=str(entry["app_key"]),
        access_token=str(entry.get("access_token") or ""),
        refresh_token=str(entry.get("refresh_token") or "") or None,
        open_id=str(entry.get("open_id") or ""),
        account=str(entry.get("account") or "") or None,
        account_type=int(entry.get("account_type") or 0),
        custom_api_domain=str(entry.get("custom_api_domain") or "") or None,
    )


def _config_id(config: AqaraCloudConfig) -> str:
    return str(getattr(config, "config_id", None) or config.id)


def _entry_name(entry: dict[str, Any]) -> str:
    return str(entry.get("device_name") or entry.get("did") or entry.get("config_id"))


def _correlation_ref(*values: Any) -> str:
    material = "\x1f".join(str(value or "") for value in values)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _entry_log_ref(entry: dict[str, Any]) -> str:
    return _correlation_ref(entry.get("config_id"), entry.get("did"), entry.get("open_id"))


def _known_private_values() -> set[str]:
    values: set[str] = set()
    for entry in registry.entries.values():
        for key in (
            "app_key",
            "access_token",
            "refresh_token",
            "auth_code",
            "config_id",
            "did",
            "device_id",
            "device_name",
            "open_id",
            "account",
        ):
            value = str(entry.get(key) or "")
            if value:
                values.add(value)
        config = entry.get("config")
        if isinstance(config, dict):
            for key in (
                "app_key",
                "access_token",
                "refresh_token",
                "auth_code",
                "config_id",
                "did",
                "device_id",
                "device_name",
                "open_id",
                "account",
            ):
                value = str(config.get(key) or "")
                if value:
                    values.add(value)
    return values


def _safe_error(exc: Exception | str) -> str:
    return str(redact_recursive(str(exc), secret_values=_known_private_values()))


def _safe_event_device(device: dict[str, Any]) -> dict[str, Any]:
    return {
        key: device.get(key)
        for key in (
            "config_id",
            "container_id",
            "integration_id",
            "device_id",
            "did",
            "device_model",
        )
        if device.get(key) is not None
    }


def _public_state_snapshots(*, diagnostics: bool = False) -> dict[str, Any]:
    return redact_recursive(
        registry.state_snapshots,
        secret_values=_known_private_values(),
        redact_pii=diagnostics,
    )


def _config_log_ref(config: AqaraCloudConfig) -> str:
    return _correlation_ref(_config_id(config), config.did, config.open_id, config.account)


def _append_runtime_event(
    *,
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> None:
    safe_device = _safe_event_device(device)
    safe_payload = redact_recursive(payload, secret_values=_known_private_values())
    registry.append_event(
        build_local_event_record(
            event_type=event_type,
            device=safe_device,
            payload=safe_payload,
            source=INTEGRATION_ID,
            severity=severity,
        )
    )


def _handle_event_delivery_error(exc: Exception, context: dict[str, Any]) -> None:
    if isinstance(exc, CoreDeliveryError):
        logger.warning("Aqara cloud event delivery failed event=%s error=%s", context.get("event_type"), _safe_error(exc))
        return
    logger.warning("Aqara cloud event delivery raised event=%s error_type=%s", context.get("event_type"), type(exc).__name__)


def _handle_event_delivery_skipped(reason: str, context: dict[str, Any]) -> None:
    logger.warning("Aqara cloud event delivery skipped event=%s reason=%s", context.get("event_type"), reason)


def _handle_telemetry_delivery_error(exc: Exception, context: dict[str, Any]) -> None:
    if isinstance(exc, CoreDeliveryError):
        logger.warning(
            "Aqara cloud telemetry delivery failed ref=%s error=%s",
            _correlation_ref(context.get("device_id")),
            _safe_error(exc),
        )
        return
    logger.warning(
        "Aqara cloud telemetry delivery raised ref=%s error_type=%s",
        _correlation_ref(context.get("device_id")),
        type(exc).__name__,
    )


def _handle_telemetry_delivery_skipped(reason: str, context: dict[str, Any]) -> None:
    logger.warning(
        "Aqara cloud telemetry delivery skipped ref=%s reason=%s",
        _correlation_ref(context.get("device_id")),
        reason,
    )


def _schedule_runtime_event_delivery(
    *,
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> None:
    safe_device = _safe_event_device(device)
    safe_payload = redact_recursive(payload, secret_values=_known_private_values())
    _append_runtime_event(event_type=event_type, device=safe_device, payload=safe_payload, severity=severity)
    schedule_event_delivery(
        process_state=runtime.process_state,
        event_client=event_client,
        auth_context=runtime.auth,
        event_type=event_type,
        device=safe_device,
        payload=safe_payload,
        source=INTEGRATION_ID,
        severity=severity,
        on_error=_handle_event_delivery_error,
        on_skipped=_handle_event_delivery_skipped,
    )


def _update_poll_status(config_id: str, **updates: Any) -> None:
    current = poll_status.get(config_id, {})
    current.update(updates)
    poll_status[config_id] = current


async def _call_with_entry_refresh(
    entry: dict[str, Any],
    operation,
):
    credentials = _entry_credentials(entry)
    try:
        return await operation(credentials)
    except AqaraCloudAuthError as initial_exc:
        if not credentials.refresh_token:
            _mark_reauth_required(entry, reason="missing_refresh_token", error=initial_exc)
            raise
        try:
            tokens = await cloud_client.refresh_access_token(credentials)
        except AqaraCloudAuthError as refresh_exc:
            _mark_reauth_required(entry, reason="refresh_token_rejected", error=refresh_exc)
            raise AqaraCloudAuthError(
                "Aqara authorization expired or was revoked. Replace the account credentials to reauthenticate."
            ) from refresh_exc
        if tokens.open_id and credentials.open_id and not hmac.compare_digest(tokens.open_id, credentials.open_id):
            identity_error = AqaraCloudAuthError(
                "Aqara token refresh returned a different account identity. Reauthenticate and verify the configured region."
            )
            _mark_reauth_required(entry, reason="account_identity_changed", error=identity_error)
            raise identity_error
        refreshed = credentials.with_tokens(tokens)
        entry["access_token"] = refreshed.access_token
        entry["refresh_token"] = refreshed.refresh_token
        entry["open_id"] = refreshed.open_id
        config = dict(entry.get("config") or {})
        config.update(
            {
                "access_token": refreshed.access_token,
                "refresh_token": refreshed.refresh_token,
                "open_id": refreshed.open_id,
            }
        )
        entry["config"] = config
        entry.update({"auth_state": "authenticated", "reauth_reason": None, "reauth_required_at": None})
        try:
            return await operation(refreshed)
        except AqaraCloudAuthError as retry_exc:
            _mark_reauth_required(entry, reason="refreshed_credentials_rejected", error=retry_exc)
            raise AqaraCloudAuthError(
                "Aqara rejected the refreshed credentials. Replace the account credentials to reauthenticate."
            ) from retry_exc


def _mark_reauth_required(entry: dict[str, Any], *, reason: str, error: Exception) -> None:
    timestamp = datetime.now(tz=UTC).isoformat()
    message = _safe_error(error)
    entry.update(
        {
            "auth_state": "reauth_required",
            "reauth_reason": reason,
            "reauth_required_at": timestamp,
        }
    )
    config_id = str(entry.get("config_id") or "")
    if config_id:
        current = _existing_state(config_id)
        current.update(
            {
                "connected": False,
                "auth_state": "reauth_required",
                "reauth_reason": reason,
                "last_error": message,
                "did": entry.get("did"),
                "device_model": entry.get("device_model"),
                "name": _entry_name(entry),
            }
        )
        registry.update_state(config_id, current)
        _update_poll_status(config_id, auth_state="reauth_required", reauth_reason=reason, last_poll_error=message)


def _capability_widgets(capabilities: list[str]) -> list[str]:
    capability_set = set(capabilities)

    def ordered(*widget_ids: str) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for widget_id in widget_ids:
            if widget_id in seen:
                continue
            seen.add(widget_id)
            result.append(widget_id)
        return result

    if "cover_position" in capability_set:
        return ordered("cover-card", "tile", "sensor-card")
    if "switch_on" in capability_set and "brightness_percent" in capability_set:
        return ordered("light-card", "tile", "sensor-card")
    if "switch_on" in capability_set:
        if capability_set & ELECTRICAL_CAPABILITIES:
            return ordered("tile", "stat", "line-chart", "sensor-card")
        return ordered("tile", "sensor-card", "stat")
    if capability_set & ELECTRICAL_CAPABILITIES:
        return ordered("stat", "line-chart", "sensor-card", "tile")
    if capability_set & CAMERA_WIDGET_CAPABILITIES:
        widgets = ["camera"]
        if capability_set & CAMERA_EVENT_CAPABILITIES:
            widgets.append("camera-events-card")
        widgets.extend(["tile", "sensor-card"])
        return ordered(*widgets)
    if capability_set & {"locked", "tamper_detected", "lock_jammed"}:
        return ordered("access-control-card", "tile", "sensor-card")
    if "battery_low" in capability_set:
        return ordered("device-health-card", "maintenance-card", "tile", "sensor-card")
    if capability_set & {"leak_detected", "smoke_alarm", "gas_alarm"}:
        return ordered("safety-overview-card", "sensor-card", "tile")
    if capability_set & {"temperature_c", "humidity_percent", "co2_ppm", "voc_ppb", "pm25_ugm3"}:
        widgets: list[str] = []
        if capability_set & {"temperature_c", "humidity_percent"}:
            widgets.append("room-climate-card")
        if capability_set & {"co2_ppm", "voc_ppb", "pm25_ugm3"}:
            widgets.append("air-quality-card")
        widgets.extend(["sensor-card", "stat", "line-chart"])
        return ordered(*widgets)
    if "presence_detected" in capability_set or "motion_detected" in capability_set:
        return ordered("presence-card", "tile", "sensor-card")
    return list(DEFAULT_ALLOWED_WIDGETS)


def _parse_number(value: str) -> int | float | None:
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return None


def _parse_boolish(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "on", "open", "yes"}:
        return True
    if lowered in {"0", "false", "off", "close", "closed", "no"}:
        return False
    number = _parse_number(lowered)
    if isinstance(number, (int, float)):
        return bool(number)
    return None


def _normalize_capability_value(capability: str, raw_value: str) -> Any:
    if capability in BOOLEAN_CAPABILITIES:
        return _parse_boolish(raw_value)
    parsed_number = _parse_number(raw_value)
    if parsed_number is not None:
        return parsed_number
    return raw_value


def _filtered_telemetry_payload(
    *,
    metrics: dict[str, Any],
    units: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    filtered_metrics = {key: value for key, value in metrics.items() if value is not None}
    if not units:
        return filtered_metrics, None
    filtered_units = {key: value for key, value in units.items() if key in filtered_metrics}
    return filtered_metrics, filtered_units or None


def _existing_state(config_id: str) -> dict[str, Any]:
    raw_snapshot = registry.state_snapshots.get(config_id)
    if isinstance(raw_snapshot, dict):
        state = raw_snapshot.get("state")
        if isinstance(state, dict):
            return dict(state)
    return {}


def _resource_bindings_for_subscription(entry: dict[str, Any]) -> list[dict[str, Any]]:
    resource_ids = sorted(
        {
            str(resource_id).strip()
            for resource_id in (entry.get("capability_bindings") or {}).values()
            if str(resource_id).strip()
        }
    )
    if not resource_ids:
        return []
    return [
        {
            "subjectId": str(entry["did"]),
            "resourceIds": resource_ids,
            "attach": str(entry.get("config_id") or ""),
        }
    ]


def _push_webhook_path() -> str:
    return "/push/aqara"


def _push_webhook_url(request: Request | None = None) -> str | None:
    if request is None:
        return None
    return str(request.url_for("aqara_push"))


def _mark_push_received(*, msg_id: str | None, message_type: str | None) -> None:
    push_status["last_received_at"] = datetime.now(tz=UTC).isoformat()
    push_status["last_msg_id"] = msg_id or None
    push_status["last_message_type"] = message_type or None
    push_status["received_count"] = int(push_status.get("received_count") or 0) + 1
    push_status["last_error"] = None


def _mark_push_processed(*, handled: int) -> None:
    push_status["last_processed_at"] = datetime.now(tz=UTC).isoformat()
    push_status["processed_count"] = int(push_status.get("processed_count") or 0) + max(int(handled), 0)


def _mark_push_duplicate() -> None:
    push_status["last_duplicate_at"] = datetime.now(tz=UTC).isoformat()
    push_status["duplicate_count"] = int(push_status.get("duplicate_count") or 0) + 1


def _mark_push_stale() -> None:
    push_status["last_stale_at"] = datetime.now(tz=UTC).isoformat()
    push_status["stale_count"] = int(push_status.get("stale_count") or 0) + 1


def _mark_push_error(message: str) -> None:
    push_status["last_error"] = message


def _is_duplicate_push(msg_id: str) -> bool:
    normalized = str(msg_id or "").strip()
    return bool(normalized) and normalized in processed_push_msg_id_set


def _remember_push_msg_id(msg_id: str) -> None:
    normalized = str(msg_id or "").strip()
    if not normalized or normalized in processed_push_msg_id_set:
        return
    processed_push_msg_id_set.add(normalized)
    processed_push_msg_ids.append(normalized)
    while len(processed_push_msg_ids) > MAX_TRACKED_PUSH_MSG_IDS:
        expired = processed_push_msg_ids.popleft()
        processed_push_msg_id_set.discard(expired)


def _push_dedupe_key(*, token: str, open_id: str, msg_id: str) -> str:
    token_fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{token_fingerprint}:{open_id}:{msg_id}"


async def _sync_resource_subscription(entry: dict[str, Any], *, subscribe: bool) -> None:
    resources = _resource_bindings_for_subscription(entry)
    if not resources:
        return
    credentials = _entry_credentials(entry)
    try:
        if subscribe:
            await cloud_client.subscribe_resources(credentials, resources=resources)
        else:
            unsubscribe_payload = [
                {
                    "subjectId": item["subjectId"],
                    "resourceIds": item["resourceIds"],
                }
                for item in resources
            ]
            await cloud_client.unsubscribe_resources(credentials, resources=unsubscribe_payload)
    except AqaraCloudError as exc:
        logger.warning(
            "Aqara resource subscription sync failed subscribe=%s ref=%s error=%s",
            subscribe,
            _entry_log_ref(entry),
            _safe_error(exc),
        )


def _schedule_state_telemetry(
    *,
    entry: dict[str, Any],
    state: dict[str, Any],
    capabilities: list[str],
    units: dict[str, str] | None,
) -> None:
    metrics = {**{cap: state.get(cap) for cap in capabilities}, "connected": bool(state.get("connected", True)), "read_failed": False}
    filtered_metrics, filtered_units = _filtered_telemetry_payload(metrics=metrics, units=units)
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry_client,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["did"]),
        metrics=filtered_metrics,
        container_id=entry.get("container_id"),
        units=filtered_units,
        timestamp=str(state.get("sampled_at") or datetime.now(tz=UTC).isoformat()),
        on_error=_handle_telemetry_delivery_error,
        on_skipped=_handle_telemetry_delivery_skipped,
    )


def _iso_timestamp_from_millis(raw_time: Any) -> str:
    try:
        millis = int(str(raw_time or "").strip())
    except (TypeError, ValueError):
        return datetime.now(tz=UTC).isoformat()
    if millis <= 0:
        return datetime.now(tz=UTC).isoformat()
    return datetime.fromtimestamp(millis / 1000.0, tz=UTC).isoformat()


def _emit_transition_event(
    *,
    entry: dict[str, Any],
    event_type: str,
    previous_value: Any,
    current_value: Any,
    sampled_at: str | None,
    capability: str,
    severity: str = "info",
) -> None:
    _schedule_runtime_event_delivery(
        event_type=event_type,
        device=entry,
        payload={
            "capability": capability,
            "previous_value": previous_value,
            "current_value": current_value,
            "sampled_at": sampled_at,
        },
        severity=severity,
    )


def _emit_camera_transition_events(
    *,
    entry: dict[str, Any],
    previous_state: dict[str, Any],
    current_state: dict[str, Any],
) -> None:
    sampled_at = str(current_state.get("sampled_at") or "")
    for capability, event_types in (
        ("motion_detected", ("aqara.camera.motion.detected", "aqara.camera.motion.cleared")),
        ("person_detected", ("aqara.camera.person.detected", "aqara.camera.person.cleared")),
        ("audio_detected", ("aqara.camera.audio.detected", "aqara.camera.audio.cleared")),
        ("doorbell_pressed", ("aqara.doorbell.pressed", "aqara.doorbell.cleared")),
        ("privacy_mode", ("aqara.camera.privacy_mode.enabled", "aqara.camera.privacy_mode.disabled")),
        ("recording_enabled", ("aqara.camera.recording.enabled", "aqara.camera.recording.disabled")),
    ):
        if capability not in previous_state or capability not in current_state:
            continue
        previous_value = previous_state.get(capability)
        current_value = current_state.get(capability)
        if previous_value == current_value:
            continue
        if not isinstance(previous_value, bool) or not isinstance(current_value, bool):
            continue
        event_type = event_types[0] if current_value else event_types[1]
        _emit_transition_event(
            entry=entry,
            event_type=event_type,
            previous_value=previous_value,
            current_value=current_value,
            sampled_at=sampled_at or None,
            capability=capability,
        )


def _emit_security_transition_events(
    *,
    entry: dict[str, Any],
    previous_state: dict[str, Any],
    current_state: dict[str, Any],
) -> None:
    sampled_at = str(current_state.get("sampled_at") or "")
    for capability, event_types, severity in (
        (
            "smoke_alarm",
            ("aqara.safety.smoke.detected", "aqara.safety.smoke.cleared"),
            "critical",
        ),
        (
            "leak_detected",
            ("aqara.safety.leak.detected", "aqara.safety.leak.cleared"),
            "warning",
        ),
        (
            "tamper_detected",
            ("aqara.access.forced_open", "aqara.access.forced_open.cleared"),
            "warning",
        ),
        (
            "lock_jammed",
            ("aqara.access.lock_jammed", "aqara.access.lock_jam.cleared"),
            "warning",
        ),
        (
            "gas_alarm",
            ("aqara.safety.gas.detected", "aqara.safety.gas.cleared"),
            "critical",
        ),
    ):
        if capability not in previous_state or capability not in current_state:
            continue
        previous_value = previous_state.get(capability)
        current_value = current_state.get(capability)
        if (
            previous_value == current_value
            or not isinstance(previous_value, bool)
            or not isinstance(current_value, bool)
        ):
            continue
        _emit_transition_event(
            entry=entry,
            event_type=event_types[0] if current_value else event_types[1],
            previous_value=previous_value,
            current_value=current_value,
            sampled_at=sampled_at or None,
            capability=capability,
            severity=severity,
        )


def _emit_device_attribute_event(
    *,
    entry: dict[str, Any],
    capability: str,
    previous_value: Any,
    current_value: Any,
    resource_id: str,
    sampled_at: str | None,
    trigger_source: dict[str, Any] | None = None,
) -> None:
    _schedule_runtime_event_delivery(
        event_type="aqara.resource_report",
        device=entry,
        payload={
            "capability": capability,
            "resource_id": resource_id,
            "previous_value": previous_value,
            "current_value": current_value,
            "sampled_at": sampled_at,
            "trigger_source": trigger_source,
        },
    )


def _persist_state(
    *,
    config_id: str,
    entry: dict[str, Any],
    state: dict[str, Any],
    units: dict[str, str] | None = None,
    emit_camera_events: bool = True,
    emit_resource_events: list[dict[str, Any]] | None = None,
) -> None:
    previous_state = _existing_state(config_id)
    current_state = redact_recursive(state, secret_values=_known_private_values())
    registry.update_state(config_id, current_state)
    if emit_camera_events and {"privacy_mode", "recording_enabled", "motion_detected", "person_detected", "audio_detected", "doorbell_pressed"} & set(current_state):
        _emit_camera_transition_events(entry=entry, previous_state=previous_state, current_state=current_state)
    _emit_security_transition_events(
        entry=entry,
        previous_state=previous_state,
        current_state=current_state,
    )
    for resource_event in emit_resource_events or []:
        capability = str(resource_event.get("capability") or "").strip()
        if not capability:
            continue
        previous_value = previous_state.get(capability)
        current_value = current_state.get(capability)
        if previous_value == current_value:
            continue
        _emit_device_attribute_event(
            entry=entry,
            capability=capability,
            previous_value=previous_value,
            current_value=current_value,
            resource_id=str(resource_event.get("resource_id") or ""),
            sampled_at=str(resource_event.get("sampled_at") or current_state.get("sampled_at") or ""),
            trigger_source=resource_event.get("trigger_source") if isinstance(resource_event.get("trigger_source"), dict) else None,
        )
    _schedule_state_telemetry(
        entry=entry,
        state=current_state,
        capabilities=list(entry.get("capabilities") or []),
        units=units,
    )


def _snapshot_timestamp(values: list[AqaraResourceValue]) -> str:
    if not values:
        return datetime.now(tz=UTC).isoformat()
    latest = max((value.timestamp_ms or 0) for value in values)
    if latest <= 0:
        return datetime.now(tz=UTC).isoformat()
    return datetime.fromtimestamp(latest / 1000.0, tz=UTC).isoformat()


def _timestamp_millis(raw_time: Any) -> int | None:
    try:
        millis = int(str(raw_time or "").strip())
    except (TypeError, ValueError):
        return None
    return millis if millis > 0 else None


def _build_snapshot(
    *,
    entry: dict[str, Any],
    resources: list[AqaraResourceInfo],
    values: list[AqaraResourceValue],
) -> dict[str, Any]:
    capability_bindings: dict[str, str] = {}
    state: dict[str, Any] = {}
    units: dict[str, str] = {}
    raw_resources: dict[str, Any] = {}
    raw_resource_timestamps_ms: dict[str, int] = {}
    resource_by_id = {resource.resource_id: resource for resource in resources}
    for value in values:
        raw_resources[value.resource_id] = value.value
        if value.timestamp_ms and value.timestamp_ms > 0:
            raw_resource_timestamps_ms[value.resource_id] = int(value.timestamp_ms)
        resource = resource_by_id.get(value.resource_id)
        if resource is None:
            continue
        capability = capability_for_resource(model=str(entry.get("device_model") or ""), resource=resource)
        if not capability or capability in capability_bindings:
            continue
        capability_bindings[capability] = value.resource_id
        state[capability] = _normalize_capability_value(capability, value.value)
        unit = CAPABILITY_UNITS.get(capability)
        if unit:
            units[capability] = unit
    state.update(
        {
            "sampled_at": _snapshot_timestamp(values),
            "connected": bool(int(entry.get("device_state") or 1)),
            "did": entry["did"],
            "device_model": entry.get("device_model"),
            "name": _entry_name(entry),
            "last_error": None,
            "raw_resources": raw_resources,
            "raw_resource_timestamps_ms": raw_resource_timestamps_ms,
        }
    )
    capabilities = sorted(capability_bindings.keys())
    command_bindings = command_bindings_for_capabilities(
        model=str(entry.get("device_model") or ""),
        resource_map=resource_by_id,
        capability_bindings=capability_bindings,
    )
    return {
        "state": state,
        "units": units,
        "capabilities": capabilities,
        "capability_bindings": capability_bindings,
        "command_bindings": command_bindings,
    }


async def _fetch_device_snapshot(entry: dict[str, Any]) -> tuple[list[AqaraResourceInfo], list[AqaraResourceValue]]:
    async def operation(credentials: AqaraCloudCredentials):
        resources = await cloud_client.resource_info(credentials, model=str(entry["device_model"]))
        values = await cloud_client.resource_values(credentials, subject_id=str(entry["did"]))
        return resources, values

    return await _call_with_entry_refresh(entry, operation)


def _update_state_snapshot(*, config_id: str, entry: dict[str, Any], snapshot: dict[str, Any]) -> None:
    entry["capabilities"] = list(snapshot["capabilities"])
    entry["capability_bindings"] = dict(snapshot["capability_bindings"])
    entry["command_bindings"] = dict(snapshot["command_bindings"])
    _persist_state(
        config_id=config_id,
        entry=entry,
        state=dict(snapshot["state"]),
        units=dict(snapshot["units"]),
    )


async def _read_and_store(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    _update_poll_status(config_id, last_poll_started=asyncio.get_running_loop().time())
    resources, values = await _fetch_device_snapshot(entry)
    snapshot = _build_snapshot(entry=entry, resources=resources, values=values)
    _update_state_snapshot(config_id=config_id, entry=entry, snapshot=snapshot)
    _update_poll_status(config_id, last_poll_succeeded=snapshot["state"]["sampled_at"], last_poll_error=None)
    return snapshot


async def _poll_config(config_id: str, interval_seconds: int) -> None:
    first_iteration = True
    while True:
        try:
            if first_iteration:
                first_iteration = False
                _update_poll_status(config_id, next_poll_due=(asyncio.get_running_loop().time() + interval_seconds))
                await asyncio.sleep(interval_seconds)
            snapshot = await _read_and_store(config_id)
            _update_poll_status(config_id, next_poll_due=(asyncio.get_running_loop().time() + interval_seconds))
            _schedule_runtime_event_delivery(
                event_type="aqara.cloud.snapshot.updated",
                device=registry.get(config_id) or {"config_id": config_id},
                payload={"sampled_at": snapshot["state"]["sampled_at"]},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            entry = registry.get(config_id)
            if entry is not None:
                error_message = _safe_error(exc)
                auth_state = str(entry.get("auth_state") or "authenticated")
                registry.update_state(
                    config_id,
                    {
                        "connected": False,
                        "did": entry["did"],
                        "device_model": entry.get("device_model"),
                        "name": _entry_name(entry),
                        "last_error": error_message,
                        "auth_state": auth_state,
                        "reauth_reason": entry.get("reauth_reason"),
                    },
                )
                schedule_telemetry_delivery(
                    process_state=runtime.process_state,
                    telemetry_client=telemetry_client,
                    auth_context=runtime.auth,
                    config_id=str(config_id),
                    device_id=str(entry["did"]),
                    metrics={"connected": False, "read_failed": True},
                    container_id=entry.get("container_id"),
                    timestamp=registry.state_snapshots.get(config_id, {}).get("last_updated"),
                    on_error=_handle_telemetry_delivery_error,
                    on_skipped=_handle_telemetry_delivery_skipped,
                )
                _schedule_runtime_event_delivery(
                    event_type="aqara.cloud.snapshot.failed",
                    device=entry,
                    payload={"error": error_message, "auth_state": auth_state},
                    severity="warning",
                )
                _update_poll_status(config_id, last_poll_error=error_message, auth_state=auth_state)
        await asyncio.sleep(interval_seconds)


async def _list_devices_with_credentials(
    credentials: AqaraCloudCredentials,
) -> tuple[list[AqaraCloudDevice], AqaraCloudCredentials]:
    try:
        return await cloud_client.list_devices(credentials), credentials
    except AqaraCloudAuthError:
        if not credentials.refresh_token:
            raise
        tokens = await cloud_client.refresh_access_token(credentials)
        if tokens.open_id and credentials.open_id and not hmac.compare_digest(tokens.open_id, credentials.open_id):
            raise AqaraCloudAuthError(
                "Aqara token refresh returned a different account identity. Reauthenticate and verify the configured region."
            )
        refreshed = credentials.with_tokens(tokens)
        return await cloud_client.list_devices(refreshed), refreshed


async def _ensure_known_device(
    config: AqaraCloudConfig,
    credentials: AqaraCloudCredentials,
) -> tuple[AqaraCloudDevice, AqaraCloudCredentials]:
    devices, active_credentials = await _list_devices_with_credentials(credentials)
    for device in devices:
        if device.did == config.did:
            return device, active_credentials
    raise HTTPException(status_code=404, detail=f"Aqara device {config.did} was not found for the provided credentials.")


async def apply_config(config: AqaraCloudConfig) -> dict[str, Any]:
    config_id = _config_id(config)
    logger.info(
        "aqara_config_apply_started ref=%s region=%s poll_interval_seconds=%s",
        _config_log_ref(config),
        config.region,
        config.poll_interval_seconds,
    )
    existing = registry.get(config_id)
    if existing is not None:
        existing_region = str(existing.get("region") or "").strip().lower()
        if existing_region != str(config.region or "").strip().lower():
            raise HTTPException(
                status_code=409,
                detail="Changing an Aqara config region in place is not allowed because region scopes account identity. Create a new config after verifying the account region.",
            )
        if str(existing.get("did") or "") != str(config.did or ""):
            raise HTTPException(status_code=409, detail="Changing the Aqara device identity (did) in place is not allowed.")
    credentials, exchanged_tokens = await _resolve_credentials(
        region=config.region,
        app_id=config.app_id,
        key_id=config.key_id,
        app_key=config.app_key,
        access_token=config.access_token,
        refresh_token=config.refresh_token,
        open_id=config.open_id,
        account=config.account,
        account_type=config.account_type,
        auth_code=config.auth_code,
        custom_api_domain=config.custom_api_domain,
    )
    device, credentials = await _ensure_known_device(config, credentials)
    for candidate_id, candidate in registry.entries.items():
        if candidate_id == config_id:
            continue
        same_device = str(candidate.get("did") or "") == config.did
        same_region = str(candidate.get("region") or "") == credentials.region
        same_account = str(candidate.get("open_id") or "") == credentials.open_id
        if same_device and same_region and same_account:
            raise HTTPException(status_code=409, detail="This Aqara account, region, and device identity is already configured.")
    if existing is not None:
        await remove_config(config_id)
    entry = {
        "config_id": config_id,
        "device_id": config.did,
        "did": config.did,
        "container_id": getattr(config, "container_id", None),
        "integration_id": getattr(config, "integration_id", None) or INTEGRATION_ID,
        "region": credentials.region,
        "app_id": credentials.app_id,
        "key_id": credentials.key_id,
        "app_key": credentials.app_key,
        "access_token": credentials.access_token,
        "refresh_token": credentials.refresh_token,
        "open_id": credentials.open_id,
        "account": credentials.account,
        "account_type": credentials.account_type,
        "did": config.did,
        "device_name": config.device_name or device.name,
        "device_model": config.device_model or device.model,
        "device_state": device.state,
        "poll_interval_seconds": config.poll_interval_seconds,
        "auth_state": "authenticated",
        "reauth_reason": None,
        "reauth_required_at": None,
        "config": {
            **config.model_dump(),
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
            "open_id": credentials.open_id,
            "auth_code": None,
        },
    }
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        {
            "connected": False,
            "did": entry["did"],
            "device_model": entry.get("device_model"),
            "name": _entry_name(entry),
        },
    )
    _update_poll_status(config_id, configured_at=registry.state_snapshots[config_id]["last_updated"])
    initial_error: str | None = None
    try:
        await _read_and_store(config_id)
        await _sync_resource_subscription(entry, subscribe=True)
    except Exception as exc:
        initial_error = _safe_error(exc)
        auth_state = str(entry.get("auth_state") or "authenticated")
        registry.update_state(
            config_id,
            {
                "connected": False,
                "did": entry["did"],
                "device_model": entry.get("device_model"),
                "name": _entry_name(entry),
                "last_error": initial_error,
                "auth_state": auth_state,
                "reauth_reason": entry.get("reauth_reason"),
            },
        )
        _schedule_runtime_event_delivery(
            event_type="aqara.cloud.initial_read.failed",
            device=entry,
            payload={"error": initial_error},
            severity="warning",
        )
    poll_tasks[config_id] = create_tracked_task(
        _poll_config(config_id, entry["poll_interval_seconds"]),
        process_state=runtime.process_state,
    )
    _schedule_runtime_event_delivery(
        event_type="device.configured",
        device=entry,
        payload={
            "did": entry["did"],
            "device_model": entry.get("device_model"),
            "used_token_exchange": exchanged_tokens is not None,
            "initial_error": initial_error,
        },
    )
    return entry


async def remove_config(config_id: str) -> bool:
    task = poll_tasks.pop(config_id, None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    removed = registry.remove(config_id)
    poll_status.pop(config_id, None)
    if removed is None:
        return False
    await _sync_resource_subscription(removed, subscribe=False)
    _schedule_runtime_event_delivery(
        event_type="device.deconfigured",
        device=removed,
        payload={"did": removed.get("did")},
    )
    return True


async def _discover_devices(
    *,
    region: str,
    app_id: str,
    key_id: str,
    app_key: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
    open_id: str | None = None,
    account: str | None = None,
    account_type: int = 0,
    auth_code: str | None = None,
    custom_api_domain: str | None = None,
    did: str | None = None,
) -> list[dict[str, Any]]:
    credentials, _tokens = await _resolve_credentials(
        region=region,
        app_id=app_id,
        key_id=key_id,
        app_key=app_key,
        access_token=access_token,
        refresh_token=refresh_token,
        open_id=open_id,
        account=account,
        account_type=account_type,
        auth_code=auth_code,
        custom_api_domain=custom_api_domain,
    )
    devices, credentials = await _list_devices_with_credentials(credentials)
    if did:
        devices = [device for device in devices if device.did == did]
    return [device.to_discovery_record(credentials=credentials) for device in devices]


def _raise_http_for_cloud_error(exc: AqaraCloudError) -> None:
    message = _safe_error(exc)
    if isinstance(exc, AqaraCloudAuthError):
        raise HTTPException(
            status_code=401,
            detail="Aqara credentials were rejected. Replace the credentials and verify the configured account region.",
        ) from exc
    if isinstance(exc, AqaraCloudRateLimitError):
        raise HTTPException(status_code=429, detail=message) from exc
    if isinstance(exc, AqaraCloudRequestError):
        raise HTTPException(status_code=502, detail=message) from exc
    raise exc


async def _extract_discovery_inputs(request: Request, payload: IntegrationDiscoveryRequest | None) -> dict[str, Any]:
    if payload is not None and isinstance(payload.inputs, dict) and payload.inputs:
        return dict(payload.inputs)
    try:
        raw_payload = await request.json()
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw_payload, dict):
        return {}
    raw_inputs = raw_payload.get("inputs")
    if isinstance(raw_inputs, dict):
        return dict(raw_inputs)
    return {key: value for key, value in raw_payload.items() if key not in {"container_id", "driver_pid"}}


def _build_entities_payload() -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for config_id, entry in registry.entries.items():
        capabilities = list(entry.get("capabilities") or [])
        widgets = _capability_widgets(capabilities)
        command_bindings = entry.get("command_bindings") or {}
        commands = [{"id": "refresh", "label": "Refresh", "kind": "action"}]
        for command_id in ("turn_on", "turn_off", "open", "close", "set_position", "set_brightness"):
            if command_id in command_bindings:
                commands.append({"id": command_id, "label": command_id.replace("_", " ").title(), "kind": "action"})
        entities.append(
            {
                "id": f"device:{config_id}",
                "name": _entry_name(entry),
                "config_id": config_id,
                "device_id": entry["did"],
                "device_class": "aqara_device",
                "entity_type": "device",
                "capabilities": capabilities + [cap for cap in ["connected", "refresh"] if cap not in capabilities],
                "available_commands": commands,
                "dashboard": {
                    "allowed_widgets": widgets,
                    "default_widget": widgets[0],
                    "recommended_widgets": widgets[:2],
                },
                "metadata": {
                    "did": entry["did"],
                    "device_model": entry.get("device_model"),
                    "region": entry.get("region"),
                },
            }
        )
    return entities


@router.get("/health")
async def health() -> RuntimeHealthResponse:
    return starter.health_response(metadata={"active_configs": len(registry.ids()), "poll_task_count": len(poll_tasks)})


@router.get("/diagnostics")
async def diagnostics(request: Request) -> RuntimeDiagnosticsResponse:
    states = [
        snapshot.get("state")
        for snapshot in registry.state_snapshots.values()
        if isinstance(snapshot, dict) and isinstance(snapshot.get("state"), dict)
    ]
    push_diagnostics_status = {key: value for key, value in push_status.items() if key != "last_msg_id"}
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "recent_event_count": len(registry.recent_events),
            "poll_task_count": len(poll_tasks),
            "poll_summary": {
                "tracked_config_count": len(poll_status),
                "error_count": sum(1 for status in poll_status.values() if status.get("last_poll_error")),
                "reauth_required_count": sum(
                    1 for status in poll_status.values() if status.get("auth_state") == "reauth_required"
                ),
            },
            "state_summary": {
                "snapshot_count": len(states),
                "connected_count": sum(1 for state in states if state.get("connected") is True),
                "disconnected_count": sum(1 for state in states if state.get("connected") is False),
                "reauth_required_count": sum(1 for state in states if state.get("auth_state") == "reauth_required"),
            },
            "push": {
                "webhook_path": _push_webhook_path(),
                "webhook_url": _push_webhook_url(request),
                "header_name": "token",
                "active_subscription_count": sum(
                    1 for entry in registry.entries.values() if _resource_bindings_for_subscription(entry)
                ),
                "status": push_diagnostics_status,
                "tracked_msg_id_count": len(processed_push_msg_id_set),
            },
        }
    )


@router.get("/ui")
@router.get("/ui-config")
async def ui_config(request: Request) -> dict[str, Any]:
    return {
        "schema": {
            "title": "Aqara Open API Setup",
            "description": "Connect PiPhi to an Aqara device by region, app credentials, and either an existing access token/open id pair or an account plus auth code.",
            "type": "object",
            "required": ["region", "app_id", "key_id", "app_key", "did"],
            "properties": {
                "region": {"type": "string", "title": "Region", "default": "us"},
                "app_id": {"type": "string", "title": "App ID"},
                "key_id": {"type": "string", "title": "Key ID"},
                "app_key": {"type": "string", "title": "App Key"},
                "access_token": {"type": "string", "title": "Access Token"},
                "refresh_token": {"type": "string", "title": "Refresh Token"},
                "open_id": {"type": "string", "title": "Open ID"},
                "account": {"type": "string", "title": "Aqara Account"},
                "account_type": {"type": "integer", "title": "Account Type", "default": 0},
                "auth_code": {"type": "string", "title": "Auth Code"},
                "did": {"type": "string", "title": "Device ID (did)"},
                "device_name": {"type": "string", "title": "Display Name"},
                "device_model": {"type": "string", "title": "Device Model"},
                "poll_interval_seconds": {"type": "integer", "title": "Poll Interval Seconds", "default": DEFAULT_POLL_INTERVAL_SECONDS, "minimum": 60}
            }
        },
        "uiSchema": {
            "app_key": {"ui:widget": "password"},
            "access_token": {"ui:widget": "password"},
            "refresh_token": {"ui:widget": "password"},
            "auth_code": {"ui:widget": "password"},
            "region": {"placeholder": "us"},
            "did": {"placeholder": "lumi.158d0000000000"},
            "poll_interval_seconds": {"help": "Aqara cloud values are not guaranteed to update more frequently than the device or hub reports them."}
        },
        "push": {
            "channel": "http",
            "webhook_path": _push_webhook_path(),
            "webhook_url": _push_webhook_url(request),
            "header_name": "token",
            "subscription_intent": "config.resource.subscribe",
            "instructions": [
                "In Aqara Developer Console, enable HTTP Push and point the push address to the webhook URL below.",
                "Aqara will send the authorized account accessToken in the token header for each push request.",
                "PiPhi subscribes the mapped device resources automatically after config succeeds.",
            ],
        },
    }


@router.get("/discover", response_model=IntegrationDiscoveryResponse)
@router.post("/discover", response_model=IntegrationDiscoveryResponse)
async def discover(request: Request, payload: IntegrationDiscoveryRequest | None = None) -> IntegrationDiscoveryResponse:
    inputs = await _extract_discovery_inputs(request, payload)
    try:
        devices = await _discover_devices(
            region=str(inputs.get("region") or "").strip(),
            app_id=str(inputs.get("app_id") or "").strip(),
            key_id=str(inputs.get("key_id") or "").strip(),
            app_key=str(inputs.get("app_key") or "").strip(),
            access_token=str(inputs.get("access_token") or "").strip() or None,
            refresh_token=str(inputs.get("refresh_token") or "").strip() or None,
            open_id=str(inputs.get("open_id") or "").strip() or None,
            account=str(inputs.get("account") or "").strip() or None,
            account_type=int(inputs.get("account_type") or 0),
            auth_code=str(inputs.get("auth_code") or "").strip() or None,
            custom_api_domain=str(inputs.get("custom_api_domain") or "").strip() or None,
            did=str(inputs.get("did") or "").strip() or None,
        )
    except AqaraCloudError as exc:
        _raise_http_for_cloud_error(exc)
    return build_discovery_response(devices)


@router.post("/config")
async def config(payload: AqaraCloudConfig, request: Request) -> RuntimeConfigApplyResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    try:
        entry = await apply_config(payload)
    except AqaraCloudError as exc:
        _raise_http_for_cloud_error(exc)
    return build_config_apply_response(
        config_id=_config_id(payload),
        container_id=entry.get("container_id"),
        metadata={"did": entry["did"], "device_model": entry.get("device_model"), "region": entry.get("region")},
    )


async def apply_runtime_config_snapshot(payload: RuntimeConfigSnapshot) -> RuntimeConfigSyncResponse:
    typed_snapshot = payload.model_copy(
        update={
            "configs": validate_typed_configs(
                [config.model_dump() if hasattr(config, "model_dump") else config for config in payload.configs],
                AqaraCloudConfig,
            ),
        }
    )
    return await config_sync.apply_snapshot(
        snapshot=typed_snapshot,
        active_config_ids=registry.ids(),
        apply_config=apply_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


@router.post("/configs/sync")
@router.post("/config/sync")
async def configs_sync(payload: RuntimeConfigSnapshot, request: Request) -> RuntimeConfigSyncResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    return await apply_runtime_config_snapshot(payload)


@router.post("/deconfigure")
async def deconfigure(payload: DeconfigurePayload, request: Request) -> RuntimeConfigRemoveResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    config_id = str(payload.config.get("config_id") or payload.config.get("id") or "").strip()
    if not config_id:
        raise HTTPException(status_code=400, detail="config_id is required.")
    removed = await remove_config(config_id)
    return build_config_remove_response(config_id=config_id, removed=removed)


@router.get("/entities")
async def entities() -> dict[str, Any]:
    return starter.entities_response(entities=_build_entities_payload()).model_dump()


@router.get("/state")
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
    safe_state_payload = redact_recursive(state_payload, secret_values=_known_private_values())
    return {
        **safe_state_payload,
        # Keep the established public shape while the SDK-owned ``entries``
        # field provides the normalized cross-integration representation.
        "state": _public_state_snapshots(),
    }


@router.get("/events", response_model=IntegrationEventListResponse)
async def events() -> IntegrationEventListResponse:
    return build_event_list_response(registry.recent_events)


def _matching_entries_for_push_token(token: str) -> list[tuple[str, dict[str, Any]]]:
    normalized = str(token or "").strip()
    if not normalized:
        return []
    matches: list[tuple[str, dict[str, Any]]] = []
    for config_id, entry in registry.entries.items():
        configured = str(entry.get("access_token") or "").strip()
        if configured and hmac.compare_digest(configured, normalized):
            matches.append((config_id, entry))
    return matches


@router.post("/push/aqara")
async def aqara_push(request: Request) -> dict[str, Any]:
    token = str(request.headers.get("token") or "").strip()
    if not token:
        _mark_push_error("missing token header")
        raise HTTPException(status_code=401, detail="Aqara push requests must include the token header.")
    matches = _matching_entries_for_push_token(token)
    if not matches:
        _mark_push_error("push token did not match any configured device")
        raise HTTPException(status_code=403, detail="Aqara push token did not match any configured device.")
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        _mark_push_error("invalid json payload")
        raise HTTPException(status_code=400, detail="Aqara push payload must be valid JSON.") from exc
    if not isinstance(payload, dict):
        _mark_push_error("push payload was not a json object")
        raise HTTPException(status_code=400, detail="Aqara push payload must be a JSON object.")

    msg_id = str(payload.get("msgId") or "").strip() or None
    msg_type = str(payload.get("msgType") or "").strip()
    event_type = str(payload.get("eventType") or "").strip()
    message_type = msg_type or event_type or "unknown"
    _mark_push_received(msg_id=msg_id, message_type=message_type)
    if not msg_id or len(msg_id) > 256:
        _mark_push_error("missing or invalid msgId")
        raise HTTPException(status_code=400, detail="Aqara push payload must include a msgId of at most 256 characters.")
    payload_open_id = str(payload.get("openId") or "").strip()
    if payload_open_id:
        matches = [
            (config_id, entry)
            for config_id, entry in matches
            if str(entry.get("open_id") or "").strip()
            and hmac.compare_digest(str(entry.get("open_id") or "").strip(), payload_open_id)
        ]
        if not matches:
            _mark_push_error("push account identity did not match token owner")
            raise HTTPException(status_code=403, detail="Aqara push account identity did not match the configured token owner.")
    dedupe_key = _push_dedupe_key(token=token, open_id=payload_open_id, msg_id=msg_id)
    async with push_dedupe_lock:
        if _is_duplicate_push(dedupe_key):
            _mark_push_duplicate()
            return {"status": "ok", "handled": 0, "duplicate": True, "message_type": message_type}
        _remember_push_msg_id(dedupe_key)
    handled = 0

    if msg_type == "resource_report":
        data_items = payload.get("data")
        if not isinstance(data_items, list):
            _mark_push_error("resource_report missing data array")
            raise HTTPException(status_code=400, detail="Aqara resource_report payload must contain a data array.")
        entries_by_did = {str(entry.get("did")): (config_id, entry) for config_id, entry in matches}
        for item in data_items:
            if not isinstance(item, dict):
                continue
            subject_id = str(item.get("subjectId") or "").strip()
            resource_id = str(item.get("resourceId") or "").strip()
            if not subject_id or not resource_id:
                continue
            match = entries_by_did.get(subject_id)
            if match is None:
                continue
            config_id, entry = match
            capability_bindings = entry.get("capability_bindings") or {}
            capability = next(
                (
                    capability_id
                    for capability_id, bound_resource_id in capability_bindings.items()
                    if str(bound_resource_id) == resource_id
                ),
                None,
            )
            if not capability:
                continue
            current_state = _existing_state(config_id)
            current_state["sampled_at"] = _iso_timestamp_from_millis(item.get("time") or payload.get("time"))
            current_state["connected"] = True
            current_state["last_error"] = None
            current_state["did"] = entry["did"]
            current_state["device_model"] = entry.get("device_model")
            current_state["name"] = _entry_name(entry)
            incoming_timestamp_ms = _timestamp_millis(item.get("time") or payload.get("time"))
            existing_timestamp_ms = _timestamp_millis(
                (current_state.get("raw_resource_timestamps_ms") or {}).get(resource_id)
            )
            if (
                incoming_timestamp_ms is not None
                and existing_timestamp_ms is not None
                and incoming_timestamp_ms < existing_timestamp_ms
            ):
                _mark_push_stale()
                continue
            raw_resources = dict(current_state.get("raw_resources") or {})
            raw_resources[resource_id] = str(item.get("value") or "")
            current_state["raw_resources"] = raw_resources
            raw_resource_timestamps_ms = dict(current_state.get("raw_resource_timestamps_ms") or {})
            if incoming_timestamp_ms is not None:
                raw_resource_timestamps_ms[resource_id] = incoming_timestamp_ms
            current_state["raw_resource_timestamps_ms"] = raw_resource_timestamps_ms
            current_state[capability] = _normalize_capability_value(capability, str(item.get("value") or ""))
            _persist_state(
                config_id=config_id,
                entry=entry,
                state=current_state,
                units={key: CAPABILITY_UNITS[key] for key in entry.get("capabilities") or [] if key in CAPABILITY_UNITS},
                emit_resource_events=[
                    {
                        "capability": capability,
                        "resource_id": resource_id,
                        "sampled_at": current_state["sampled_at"],
                        "trigger_source": item.get("triggerSource"),
                    }
                ],
            )
            handled += 1
        _mark_push_processed(handled=handled)
        return {"status": "ok", "handled": handled, "duplicate": False, "message_type": msg_type}

    if event_type == "control_fail":
        data = payload.get("data")
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            subject_id = str(item.get("subjectId") or "").strip()
            for _config_id, entry in matches:
                if str(entry.get("did")) != subject_id:
                    continue
                _schedule_runtime_event_delivery(
                    event_type="aqara.control.failed",
                    device=entry,
                    payload={"message": payload, "data": item},
                    severity="warning",
                )
                handled += 1
        _mark_push_processed(handled=handled)
        return {"status": "ok", "handled": handled, "duplicate": False, "message_type": event_type}

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    did = str(data.get("did") or "").strip()
    for config_id, entry in matches:
        if did and str(entry.get("did")) != did:
            continue
        if event_type in {"subdevice_online", "gateway_online"}:
            current_state = _existing_state(config_id)
            current_state.update(
                {
                    "connected": True,
                    "sampled_at": _iso_timestamp_from_millis(data.get("time") or payload.get("time")),
                    "last_error": None,
                    "did": entry["did"],
                    "device_model": entry.get("device_model"),
                    "name": _entry_name(entry),
                }
            )
            _persist_state(
                config_id=config_id,
                entry=entry,
                state=current_state,
                units={key: CAPABILITY_UNITS[key] for key in entry.get("capabilities") or [] if key in CAPABILITY_UNITS},
                emit_camera_events=False,
            )
            _schedule_runtime_event_delivery(event_type=f"aqara.{event_type}", device=entry, payload=payload)
            handled += 1
        elif event_type in {"subdevice_offline", "gateway_offline"}:
            current_state = _existing_state(config_id)
            current_state.update(
                {
                    "connected": False,
                    "sampled_at": _iso_timestamp_from_millis(data.get("time") or payload.get("time")),
                    "did": entry["did"],
                    "device_model": entry.get("device_model"),
                    "name": _entry_name(entry),
                }
            )
            _persist_state(
                config_id=config_id,
                entry=entry,
                state=current_state,
                units={key: CAPABILITY_UNITS[key] for key in entry.get("capabilities") or [] if key in CAPABILITY_UNITS},
                emit_camera_events=False,
            )
            _schedule_runtime_event_delivery(event_type=f"aqara.{event_type}", device=entry, payload=payload, severity="warning")
            handled += 1
        elif event_type == "dev_name_change":
            device_name = str(data.get("deviceName") or "").strip()
            if device_name:
                entry["device_name"] = device_name
                current_state = _existing_state(config_id)
                current_state["name"] = device_name
                current_state["sampled_at"] = _iso_timestamp_from_millis(data.get("time") or payload.get("time"))
                _persist_state(
                    config_id=config_id,
                    entry=entry,
                    state=current_state,
                    units={key: CAPABILITY_UNITS[key] for key in entry.get("capabilities") or [] if key in CAPABILITY_UNITS},
                    emit_camera_events=False,
                )
            _schedule_runtime_event_delivery(event_type="aqara.dev_name_change", device=entry, payload=payload)
            handled += 1
    _mark_push_processed(handled=handled)
    return {"status": "ok", "handled": handled, "duplicate": False, "message_type": event_type or msg_type or "unknown"}


def _resolve_command_config_id(payload: IntegrationCommandRequest) -> str:
    config_id = str(payload.args.get("config_id") or "").strip()
    if not config_id:
        config_id = str(payload.config_id or "").strip()
    if not config_id and payload.entity_id and payload.entity_id.startswith("device:"):
        config_id = payload.entity_id.split(":", 1)[1]
    if not config_id and payload.device_id:
        for candidate_id, entry in registry.entries.items():
            if str(entry.get("did")) == str(payload.device_id):
                config_id = candidate_id
                break
    if not config_id:
        raise HTTPException(status_code=400, detail="Command must include config_id, entity_id, or device_id.")
    return config_id


def _validate_command_request(
    payload: IntegrationCommandRequest,
    config_id: str,
) -> None:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    if payload.command == "refresh":
        return
    if payload.command not in AUTOMATION_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {payload.command}")
    binding = (entry.get("command_bindings") or {}).get(payload.command)
    if not binding:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {payload.command}")
    if binding.get("dynamic"):
        requested_value = payload.args.get("position") if payload.command == "set_position" else payload.args.get("value")
        if requested_value is None:
            raise HTTPException(status_code=400, detail=f"{payload.command} requires args.position or args.value.")
        _bounded_dynamic_value(requested_value, binding=binding, command=payload.command)


def _bounded_dynamic_value(value: Any, *, binding: dict[str, Any], command: str) -> str:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{command} requires a finite numeric percentage.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{command} requires a finite numeric percentage.") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise HTTPException(status_code=400, detail=f"{command} requires a whole-number percentage.")
    minimum = int(binding.get("min_value", 0))
    maximum = int(binding.get("max_value", 100))
    integer = int(numeric)
    if integer < minimum or integer > maximum:
        raise HTTPException(status_code=400, detail=f"{command} must be between {minimum} and {maximum}.")
    return str(integer)


async def _execute_registered_command(
    action_request: AutomationActionRequest,
) -> AutomationActionResult:
    config_id = str(action_request.config_id or "").strip()
    entry = registry.get(config_id)
    if entry is None:
        return AutomationActionResult.failure(
            f"unknown config_id={config_id}",
            metadata={"status_code": 404},
        )

    if action_request.command == "refresh":
        try:
            snapshot = await _read_and_store(config_id)
        except HTTPException as exc:
            return AutomationActionResult.failure(
                str(exc.detail),
                retryable=exc.status_code >= 500,
                metadata={"status_code": exc.status_code},
            )
        except AqaraCloudError as exc:
            status_code = 401 if isinstance(exc, AqaraCloudAuthError) else 429 if isinstance(exc, AqaraCloudRateLimitError) else 502
            return AutomationActionResult.failure(
                _safe_error(exc),
                retryable=status_code in {429, 502},
                metadata={"status_code": status_code},
            )
        return AutomationActionResult.success(
            {
                "status": "ok",
                "config_id": config_id,
                "sampled_at": snapshot["state"]["sampled_at"],
                "state": redact_recursive(
                    registry.state_snapshots.get(config_id, {}).get("state"),
                    secret_values=_known_private_values(),
                ),
            }
        )

    binding = (entry.get("command_bindings") or {}).get(action_request.command)
    if not binding:
        return AutomationActionResult.failure(
            f"Unsupported command: {action_request.command}",
            metadata={"status_code": 400},
        )
    value = str(binding.get("value") or "")
    if binding.get("dynamic"):
        requested_value = action_request.args.get("position") if action_request.command == "set_position" else action_request.args.get("value")
        if requested_value is None:
            return AutomationActionResult.failure(
                f"{action_request.command} requires args.position or args.value.",
                metadata={"status_code": 400},
            )
        try:
            value = _bounded_dynamic_value(requested_value, binding=binding, command=action_request.command)
        except HTTPException as exc:
            return AutomationActionResult.failure(str(exc.detail), metadata={"status_code": exc.status_code})

    async def operation(credentials: AqaraCloudCredentials):
        await cloud_client.write_resource(
            credentials,
            subject_id=str(entry["did"]),
            resource_id=str(binding["resource_id"]),
            value=value,
        )
    try:
        await _call_with_entry_refresh(entry, operation)
        snapshot = await _read_and_store(config_id)
    except AqaraCloudError as exc:
        try:
            _raise_http_for_cloud_error(exc)
        except HTTPException as http_exc:
            return AutomationActionResult.failure(
                str(http_exc.detail),
                retryable=http_exc.status_code >= 500 or http_exc.status_code == 429,
                metadata={"status_code": http_exc.status_code},
            )
        return AutomationActionResult.failure(_safe_error(exc), metadata={"status_code": 500})
    return AutomationActionResult.success(
        {
            "status": "ok",
            "config_id": config_id,
            "command": action_request.command,
            "state": redact_recursive(snapshot["state"], secret_values=_known_private_values()),
        }
    )


for _command_name in sorted(AUTOMATION_COMMANDS):
    automation_registry.action(_command_name)(_execute_registered_command)


@router.post("/command")
async def command(payload: IntegrationCommandRequest, request: Request) -> dict[str, Any]:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    config_id = _resolve_command_config_id(payload)
    _validate_command_request(payload, config_id)
    normalized_payload = {
        **payload.model_dump(mode="python"),
        "config_id": config_id,
        "device_id": str((registry.get(config_id) or {}).get("did") or payload.device_id or "") or None,
    }
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        normalized_payload,
    )
    if not result.ok:
        raise HTTPException(
            status_code=int(result.metadata.get("status_code") or 503),
            detail=result.error,
        )
    return {**result.result, "replayed": result.replayed}
