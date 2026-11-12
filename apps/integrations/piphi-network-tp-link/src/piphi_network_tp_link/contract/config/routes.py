import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    ConfigSyncCoordinator,
    EventClient,
    RuntimeConfigApplyResponse,
    RuntimeConfigRemoveResponse,
    TelemetryClient,
    build_config_apply_response,
    build_config_remove_response,
    create_tracked_task,
    format_config_apply_log,
    format_runtime_auth_sync_log,
    resolve_core_base_url,
    schedule_event_delivery,
    schedule_telemetry_delivery,
    shutdown_background_tasks as shutdown_runtime_background_tasks,
)
from piphi_runtime_kit_python.fastapi import (
    get_payload_container_id,
    sync_runtime_auth_from_fastapi_payload,
)

from piphi_network_tp_link.lib.kasa_client import execute_device_command, fetch_device_state
from piphi_network_tp_link.lib.logging import logger
from piphi_network_tp_link.lib.schemas import (
    DeconfigureConfig,
    RuntimeConfigSnapshot,
    RuntimeConfigSyncResponse,
    TPLinkDeviceConfig,
)
from piphi_network_tp_link.lib.store import (
    append_event,
    get_runtime_context,
    registry,
    update_device_state,
)

config_router = APIRouter(tags=["config"])

CORE_BASE_URL = resolve_core_base_url("http://127.0.0.1:31419")
POLL_INTERVAL_SECONDS = 30
TELEMETRY_REQUEST_TIMEOUT_SECONDS = 3.0
EVENT_REQUEST_TIMEOUT_SECONDS = 3.0
runtime_context = get_runtime_context()
telemetry_client = TelemetryClient(
    process_state=runtime_context.process_state,
    core_base_url=CORE_BASE_URL,
    timeout_seconds=TELEMETRY_REQUEST_TIMEOUT_SECONDS,
)
event_client = EventClient(
    process_state=runtime_context.process_state,
    core_base_url=CORE_BASE_URL,
    timeout_seconds=EVENT_REQUEST_TIMEOUT_SECONDS,
)
config_sync = ConfigSyncCoordinator(process_state=runtime_context.process_state)


def _entry_id_for_config(payload: TPLinkDeviceConfig) -> str:
    return str(payload.config_id or payload.id).strip()


def _physical_device_id_for_config(payload: TPLinkDeviceConfig, entry_id: str) -> str:
    for value in (
        getattr(payload, "physical_device_id", None),
        payload.id,
        getattr(payload, "device_id", None),
    ):
        candidate = str(value or "").strip()
        if candidate and candidate != entry_id:
            return candidate
    return entry_id


def _normalize_snapshot_config(config: TPLinkDeviceConfig) -> TPLinkDeviceConfig:
    entry_id = _entry_id_for_config(config)
    if not entry_id or str(config.id or "").strip() == entry_id:
        return config
    return config.model_copy(
        update={
            "id": entry_id,
            "physical_device_id": _physical_device_id_for_config(config, entry_id),
        }
    )


def schedule_event_send(
    *,
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    source: str = "tp_link_kasa_runtime",
    severity: str = "info",
) -> None:
    schedule_event_delivery(
        process_state=runtime_context.process_state,
        event_client=event_client,
        auth_context=runtime_context.auth,
        event_type=event_type,
        device=device,
        payload=payload,
        source=source,
        severity=severity,
        record_event=append_event,
        on_skipped=lambda reason, details: logger.debug(
            "event_send_skipped "
            f"reason={reason} "
            f"event_type={details.get('event_type') or event_type} "
            f"device_id={details.get('device_id') or 'unknown'}"
        ),
        on_error=lambda exc, details: logger.exception(
            "event_send_unexpected_error "
            f"event_type={details.get('event_type') or event_type} "
            f"device_id={details.get('device_id') or 'unknown'} "
            f"error={exc}"
        ),
    )


async def shutdown_background_tasks() -> None:
    await shutdown_runtime_background_tasks(runtime_context.process_state)


def _sync_runtime_auth_from_request(request: Request, payload: Any | None = None) -> None:
    parsed_headers = sync_runtime_auth_from_fastapi_payload(
        runtime_context,
        request,
        payload,
    )

    logger.info(
        format_runtime_auth_sync_log(
            parsed_headers,
            payload_container_id=get_payload_container_id(payload),
        )
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_telemetry_metrics(telemetry_data: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "switch": bool(telemetry_data.get("is_on", False)),
        "is_on": bool(telemetry_data.get("is_on", False)),
        "device_type": telemetry_data.get("device_type"),
        "model": telemetry_data.get("model"),
        "signal_strength": telemetry_data.get("signal_strength"),
    }

    current_power_w = _safe_float(telemetry_data.get("current_power_w"))
    today_kwh = _safe_float(telemetry_data.get("today_kwh"))
    month_kwh = _safe_float(telemetry_data.get("month_kwh"))

    energy = telemetry_data.get("energy") or {}
    features = telemetry_data.get("features") or {}
    if current_power_w is None:
        current_power_w = _safe_float(energy.get("current_power_w"))
    if today_kwh is None:
        today_kwh = _safe_float(energy.get("today_kwh"))
    if month_kwh is None:
        month_kwh = _safe_float(energy.get("month_kwh"))

    if current_power_w is not None:
        metrics["power"] = current_power_w
        metrics["energy_power"] = current_power_w
        metrics["current_power_w"] = current_power_w
    if today_kwh is not None:
        metrics["energy_today"] = today_kwh
        metrics["today_kwh"] = today_kwh
    if month_kwh is not None:
        metrics["energy_this_month"] = month_kwh
        metrics["month_kwh"] = month_kwh

    for capability, candidates in {
        "brightness": ("brightness", "dimming"),
        "color_temperature": ("color_temperature", "color_temp"),
        "temperature": ("temperature",),
        "humidity": ("humidity",),
    }.items():
        for feature_id, feature in features.items():
            normalized_id = str(feature_id).strip().lower()
            if not any(candidate in normalized_id for candidate in candidates):
                continue
            value = _safe_float(
                feature.get("value") if isinstance(feature, dict) else None
            )
            if value is not None:
                metrics[capability] = value
                break

    return {key: value for key, value in metrics.items() if value is not None}

async def fetch_and_store_state(
    *,
    host: str,
    device_id: str,
    container_id: str | None,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    device_entry = registry.get(device_id) or {}
    previous_state = device_entry.get("latest_state") or {}
    payload = await fetch_device_state(host=host, username=username, password=password)
    latest_state = update_device_state(device_id=device_id, state=payload)
    if container_id:
        schedule_telemetry_delivery(
            process_state=runtime_context.process_state,
            telemetry_client=telemetry_client,
            auth_context=runtime_context.auth,
            config_id=str(device_entry.get("config_id") or device_id),
            device_id=device_id,
            metrics=_build_telemetry_metrics(payload),
            container_id=container_id,
            units={
                "brightness": "%",
                "color_temperature": "K",
                "power": "W",
                "energy_power": "W",
                "energy_today": "kWh",
                "energy_this_month": "kWh",
                "signal_strength": "dBm",
                "current_power_w": "W",
                "today_kwh": "kWh",
                "month_kwh": "kWh",
            },
            on_skipped=lambda reason, details: logger.warning(
                "telemetry_send_skipped "
                f"reason={reason} "
                f"device_id={details.get('device_id') or device_id}"
            ),
            on_error=lambda exc, details: logger.exception(
                "telemetry_send_unexpected_error "
                f"device_id={details.get('device_id') or device_id} "
                f"error={exc}"
            ),
        )
        if registry.get(device_id) is not None:
            previous_is_on = bool(previous_state.get("is_on")) if previous_state else None
            current_is_on = bool(payload.get("is_on"))
            if previous_is_on is not None and previous_is_on != current_is_on:
                device_entry = registry.get(device_id) or {}
                schedule_event_send(
                    event_type="device.turned_on" if current_is_on else "device.turned_off",
                    device=device_entry,
                    payload={
                        "alias": device_entry.get("alias"),
                        "host": host,
                        "is_on": current_is_on,
                    },
                )
    return latest_state


def start_device_poll_task(
    *,
    host: str,
    device_id: str,
    container_id: str | None,
    username: str | None = None,
    password: str | None = None,
) -> asyncio.Task[Any]:
    return create_tracked_task(
        poll_device_state(
            host=host,
            device_id=device_id,
            container_id=container_id,
            username=username,
            password=password,
        ),
        process_state=runtime_context.process_state,
    )


async def run_command_for_device(
    *,
    device_id: str,
    command: str,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    device = registry.get(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' is not configured")

    try:
        result = await execute_device_command(
            host=device["host"],
            command=command,
            args=args or {},
            username=device.get("username"),
            password=device.get("password"),
        )
        schedule_event_send(
            event_type="device.command.executed",
            device=device,
            payload={
                "command": command,
                "args": args or {},
                "host": device.get("host"),
            },
        )
        return result
    except Exception as exc:
        schedule_event_send(
            event_type="device.command.failed",
            device=device,
            payload={
                "command": command,
                "args": args or {},
                "host": device.get("host"),
                "error": str(exc),
            },
            severity="error",
        )
        raise HTTPException(status_code=400, detail=f"Command failed: {exc}") from exc


async def trigger_refresh(device_id: str) -> dict[str, Any]:
    device = registry.get(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' is not configured")

    try:
        return await fetch_and_store_state(
            host=device["host"],
            device_id=device_id,
            container_id=device.get("container_id"),
            username=device.get("username"),
            password=device.get("password"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Refresh failed: {exc}") from exc


async def poll_device_state(
    *,
    host: str,
    device_id: str,
    container_id: str | None,
    username: str | None = None,
    password: str | None = None,
) -> None:
    while True:
        try:
            await fetch_and_store_state(
                host=host,
                device_id=device_id,
                container_id=container_id,
                username=username,
                password=password,
            )
            logger.info(f"state_poll_success device_id={device_id} host={host}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"state_poll_error device_id={device_id} host={host} error={exc}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def remove_device_config(device_id: str) -> bool:
    existing_poll = registry.get(device_id)
    if existing_poll and existing_poll.get("task") and not existing_poll["task"].done():
        existing_poll["task"].cancel()
        try:
            await existing_poll["task"]
        except asyncio.CancelledError:
            pass

    removed = registry.get(device_id) is not None
    if existing_poll is not None:
        schedule_event_send(
            event_type="device.deconfigured",
            device=existing_poll,
            payload={
                "alias": existing_poll.get("alias"),
                "host": existing_poll.get("host"),
            },
        )
    registry.remove(device_id)
    return removed


async def apply_device_config(payload: TPLinkDeviceConfig) -> dict[str, Any]:
    logger.info(format_config_apply_log(payload))
    resolved_container_id, _ = runtime_context.auth.resolve(container_id=payload.container_id)
    entry_id = _entry_id_for_config(payload)
    physical_device_id = _physical_device_id_for_config(payload, entry_id)

    await remove_device_config(entry_id)
    task = start_device_poll_task(
        host=payload.host,
        device_id=entry_id,
        container_id=resolved_container_id,
        username=payload.username,
        password=payload.password,
    )
    registry.set(entry_id, {
        "task": task,
        "config_id": entry_id,
        "container_id": resolved_container_id,
        "device_id": entry_id,
        "physical_device_id": physical_device_id,
        "host": payload.host,
        "alias": payload.alias,
        "integration_id": payload.integration_id,
        "username": payload.username,
        "password": payload.password,
    })

    try:
        await trigger_refresh(entry_id)
    except HTTPException as exc:
        logger.warning(f"kasa_initial_refresh_failed device_id={entry_id} detail={exc.detail}")

    device_entry = registry.get(entry_id) or {}
    schedule_event_send(
        event_type="device.configured",
        device=device_entry,
        payload={
            "alias": payload.alias,
            "host": payload.host,
            "physical_device_id": physical_device_id,
            "model": device_entry.get("latest_state", {}).get("model"),
        },
    )

    return build_config_apply_response(
        config_id=entry_id,
        container_id=resolved_container_id,
        metadata={"host": payload.host},
    ).model_dump()


async def apply_runtime_config_snapshot(payload: RuntimeConfigSnapshot) -> RuntimeConfigSyncResponse:
    normalized_payload = payload.model_copy(
        update={"configs": [_normalize_snapshot_config(config) for config in payload.configs]}
    )

    async def apply_config_with_context(config: TPLinkDeviceConfig) -> dict[str, Any]:
        effective_config = config.model_copy(
            update={
                "integration_id": config.integration_id or normalized_payload.integration_id,
                "container_id": config.container_id or normalized_payload.container_id,
            }
        )
        return await apply_device_config(effective_config)

    response = await config_sync.apply_snapshot(
        snapshot=normalized_payload,
        active_config_ids=registry.ids(),
        apply_config=apply_config_with_context,
        remove_config=remove_device_config,
        get_active_config_ids=registry.ids,
    )
    return RuntimeConfigSyncResponse(**response.model_dump())


@config_router.post("/config")
async def config(payload: TPLinkDeviceConfig, request: Request) -> RuntimeConfigApplyResponse:
    _sync_runtime_auth_from_request(request, payload)
    return RuntimeConfigApplyResponse.model_validate(await apply_device_config(payload))


@config_router.post("/configs/sync", response_model=RuntimeConfigSyncResponse)
async def sync_configs(payload: RuntimeConfigSnapshot, request: Request) -> RuntimeConfigSyncResponse:
    _sync_runtime_auth_from_request(request, payload)
    return await apply_runtime_config_snapshot(payload)


@config_router.post("/config/sync", response_model=RuntimeConfigSyncResponse)
async def sync_config(payload: RuntimeConfigSnapshot, request: Request) -> RuntimeConfigSyncResponse:
    _sync_runtime_auth_from_request(request, payload)
    return await apply_runtime_config_snapshot(payload)


@config_router.post("/deconfigure")
async def deconfigure_device(payload: DeconfigureConfig) -> RuntimeConfigRemoveResponse:
    device_id = payload.config.get("id")
    if device_id is None:
        raise HTTPException(status_code=400, detail="Missing config id")

    removed = await remove_device_config(device_id)
    if not removed:
        logger.info(f"deconfigure_noop device_id={device_id}")

    return build_config_remove_response(
        config_id=str(device_id),
        removed=removed,
    )
