from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
)

from .contract import CAPABILITIES, COMMANDS
from .normalization import ClimatePoint, normalize_devices, opaque_id
from .onecta import AccountSnapshot, OnectaClient, OnectaError, Quota
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

logger = logging.getLogger(__name__)
MASKED_SECRETS = {"********", "••••••••"}

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


@dataclass(slots=True)
class OnectaRuntimeData:
    configs: dict[str, DeviceConfig] = field(default_factory=dict)
    clients: dict[str, OnectaClient] = field(default_factory=dict)
    locators: dict[str, dict[str, tuple[str, str, str]]] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    client_factory: Callable[..., OnectaClient] = OnectaClient


runtime_data = OnectaRuntimeData()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def append_runtime_event(
    event_type: str, device: dict[str, Any], payload: dict[str, Any] | None = None
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
        raise HTTPException(status_code=404, detail={"error": "unknown_configuration"})
    return entry


def _resolved_config(config: DeviceConfig) -> DeviceConfig:
    config_id = str(config.config_id or config.id)
    if config.access_token.get_secret_value() not in MASKED_SECRETS:
        return config
    previous = runtime_data.configs.get(config_id)
    if previous is None or previous.oauth_subject != config.oauth_subject:
        raise HTTPException(status_code=422, detail={"error": "access_token_required"})
    return config.model_copy(update={"access_token": previous.access_token})


def _quota_dict(quota: Quota) -> dict[str, Any]:
    return {
        "minute_remaining": quota.minute_remaining,
        "day_remaining": quota.day_remaining,
        "reset_at": quota.reset_at,
        "retry_after_seconds": quota.retry_after_seconds,
    }


def _point_dict(point: ClimatePoint) -> dict[str, Any]:
    return {
        "device_id": f"{INTEGRATION_ID}:{point.device_id}",
        "name": point.name,
        "model": point.model,
        "connected": point.connected,
        "power": point.power,
        "hvac_mode": point.hvac_mode,
        "indoor_temperature_c": point.indoor_temperature_c,
        "target_temperature_c": point.target_temperature_c,
        "target_temperature_min_c": point.target_temperature_min_c,
        "target_temperature_max_c": point.target_temperature_max_c,
        "target_temperature_step_c": point.target_temperature_step_c,
        "target_settable": point.target_settable,
    }


def _point_locators(points: list[ClimatePoint]) -> dict[str, tuple[str, str, str]]:
    return {
        f"{INTEGRATION_ID}:{point.device_id}": (
            point.gateway_id,
            point.management_point_id,
            point.target_path,
        )
        for point in points
        if point.target_path is not None
    }


def _make_entry(
    config: DeviceConfig, snapshot: AccountSnapshot, points: list[ClimatePoint]
) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "device_id": f"{INTEGRATION_ID}:account:{opaque_id(config.oauth_subject)}",
        "oauth_subject_hash": opaque_id(config.oauth_subject),
        "alias": config.alias or "Daikin Onecta account",
        "config": {
            "id": config.id,
            "config_id": str(config.config_id or config.id),
            "container_id": config.container_id,
            "alias": config.alias,
            "poll_interval_seconds": config.poll_interval_seconds,
            "enable_climate_control": config.enable_climate_control,
        },
        "poll_interval_seconds": config.poll_interval_seconds,
        "enable_climate_control": config.enable_climate_control,
        "climate_points": [_point_dict(point) for point in points],
        "quota": _quota_dict(snapshot.quota),
        "next_poll_at": time.monotonic() + config.poll_interval_seconds,
        "consecutive_failures": 0,
        "availability": "online",
        "last_success_at": _now(),
        "last_error_category": None,
    }


def _setup_error(exc: Exception) -> HTTPException:
    category = exc.category if isinstance(exc, OnectaError) else "provider_unavailable"
    status = (
        401
        if category == "invalid_auth"
        else 403
        if category == "permission_denied"
        else 503
    )
    return HTTPException(status_code=status, detail={"error": category})


async def _close_client(client: OnectaClient, config_id: str) -> None:
    try:
        await client.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "onecta_close_failed config_id=%s error=%s", config_id, type(exc).__name__
        )


async def _discard_client(config_id: str) -> None:
    client = runtime_data.clients.pop(config_id, None)
    if client is not None:
        await _close_client(client, config_id)
    runtime_data.locators.pop(config_id, None)


async def apply_config(config: DeviceConfig) -> None:
    config = _resolved_config(config)
    config_id = str(config.config_id or config.id)
    candidate = runtime_data.client_factory(config.access_token.get_secret_value())
    try:
        snapshot = await candidate.fetch_devices()
        points = normalize_devices(config.oauth_subject, snapshot.devices)
        entry = _make_entry(config, snapshot, points)
    except Exception as exc:  # noqa: BLE001 - candidate transport must always close
        await _close_client(candidate, config_id)
        raise _setup_error(exc) from None

    old_client: OnectaClient | None = None
    try:
        async with runtime_data.config_lock:
            duplicate = next(
                (
                    item
                    for other_id, item in registry.entries.items()
                    if other_id != config_id
                    and item.get("oauth_subject_hash") == entry["oauth_subject_hash"]
                ),
                None,
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=409, detail={"error": "account_already_configured"}
                )
            previous = registry.get(config_id)
            if (
                previous is not None
                and previous.get("oauth_subject_hash") != entry["oauth_subject_hash"]
            ):
                raise HTTPException(
                    status_code=409, detail={"error": "account_identity_mismatch"}
                )
            old_client = runtime_data.clients.get(config_id)
            runtime_data.configs[config_id] = config
            runtime_data.clients[config_id] = candidate
            runtime_data.locators[config_id] = _point_locators(points)
            runtime_data.locks.setdefault(config_id, asyncio.Lock())
            registry.set(config_id, entry)
            _publish_success(entry)
    except Exception:
        await _close_client(candidate, config_id)
        raise
    if old_client is not None and old_client is not candidate:
        await _close_client(old_client, config_id)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {
            "climate_count": len(entry["climate_points"]),
            "reconfigured": old_client is not None,
        },
    )


async def remove_config(config_id: str) -> bool:
    async with runtime_data.config_lock:
        lock = runtime_data.locks.setdefault(config_id, asyncio.Lock())
        async with lock:
            runtime_data.configs.pop(config_id, None)
            await _discard_client(config_id)
            entry = registry.remove(config_id)
        runtime_data.locks.pop(config_id, None)
    if entry is None:
        return False
    append_runtime_event("runtime.config.removed", entry)
    return True


def _publish_success(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    now = _now()
    entry.update(
        availability="online",
        last_success_at=now,
        last_error_category=None,
        consecutive_failures=0,
    )
    states = []
    for point in entry["climate_points"]:
        state = {
            "device_id": point["device_id"],
            "connected": point["connected"],
            "available": point["connected"],
            "stale": False,
            "power": point["power"],
            "hvac_mode": point["hvac_mode"],
            "indoor_temperature_c": point["indoor_temperature_c"],
            "target_temperature_c": point["target_temperature_c"],
            "last_success_at": now,
        }
        states.append(state)
        metrics = {
            key: value
            for key, value in state.items()
            if key not in {"device_id", "last_success_at"} and value is not None
        }
        schedule_telemetry_delivery(
            process_state=runtime.process_state,
            telemetry_client=telemetry,
            auth_context=runtime.auth,
            config_id=config_id,
            device_id=str(point["device_id"]),
            container_id=entry.get("container_id"),
            metrics=metrics,
            units={"indoor_temperature_c": "C", "target_temperature_c": "C"},
        )
    account_state = {
        "connected": True,
        "available": True,
        "stale": False,
        "climate_count": len(states),
        "devices": states,
        "quota": entry["quota"],
        "last_success_at": now,
    }
    registry.update_state(config_id, account_state, device_id=entry["device_id"])
    return account_state


def _next_delay(entry: dict[str, Any]) -> int:
    interval = int(entry["poll_interval_seconds"])
    failures = int(entry.get("consecutive_failures", 0))
    delay = min(3600, interval * (2 ** min(failures, 4)))
    quota = entry.get("quota") or {}
    if quota.get("retry_after_seconds") is not None:
        delay = max(delay, int(quota["retry_after_seconds"]))
    if quota.get("minute_remaining") == 0:
        delay = max(delay, 60)
    if quota.get("day_remaining") == 0:
        delay = max(delay, 3600)
    return min(86400, delay)


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        client = runtime_data.clients.get(config_id)
        config = runtime_data.configs.get(config_id)
        try:
            if client is None or config is None:
                raise OnectaError("configuration_unavailable")
            snapshot = await client.fetch_devices()
            points = normalize_devices(config.oauth_subject, snapshot.devices)
            entry["climate_points"] = [_point_dict(point) for point in points]
            runtime_data.locators[config_id] = _point_locators(points)
            entry["quota"] = _quota_dict(snapshot.quota)
        except Exception as exc:  # noqa: BLE001
            category = (
                exc.category if isinstance(exc, OnectaError) else "provider_unavailable"
            )
            was_online = entry.get("availability") == "online"
            entry["consecutive_failures"] = (
                int(entry.get("consecutive_failures", 0)) + 1
            )
            entry["last_error_category"] = category
            entry["availability"] = (
                "reauth_required" if category == "invalid_auth" else "unavailable"
            )
            if isinstance(exc, OnectaError) and exc.retry_after_seconds is not None:
                entry.setdefault("quota", {})["retry_after_seconds"] = (
                    exc.retry_after_seconds
                )
            prior = registry.state_snapshots.get(config_id, {}).get("state", {})
            state = {
                **prior,
                "connected": False,
                "available": False,
                "stale": True,
                "error_category": category,
            }
            if isinstance(state.get("devices"), list):
                state["devices"] = [
                    {**item, "connected": False, "available": False, "stale": True}
                    for item in state["devices"]
                ]
            registry.update_state(config_id, state, device_id=entry["device_id"])
            if was_online:
                append_runtime_event(
                    "onecta.account.unavailable", entry, {"category": category}
                )
        else:
            was_offline = entry.get("availability") != "online"
            state = _publish_success(entry)
            if was_offline:
                append_runtime_event("onecta.account.recovered", entry)
        entry["next_poll_at"] = (
            float("inf")
            if entry.get("availability") == "reauth_required"
            else time.monotonic() + _next_delay(entry)
        )
        return state


def _temperature_is_on_step(value: float, minimum: float, step: float) -> bool:
    return math.isclose(
        (value - minimum) / step, round((value - minimum) / step), abs_tol=1e-7
    )


async def set_target_temperature(
    config_id: str, device_id: str, value: float
) -> dict[str, Any]:
    entry = get_entry_or_404(config_id)
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        if not entry.get("enable_climate_control"):
            raise HTTPException(
                status_code=403, detail={"error": "climate_control_disabled"}
            )
        if entry.get("availability") != "online":
            raise HTTPException(
                status_code=409, detail={"error": "account_unavailable"}
            )
        matches = [
            point
            for point in entry["climate_points"]
            if point["device_id"] == device_id
        ]
        if len(matches) != 1:
            raise HTTPException(
                status_code=404, detail={"error": "unknown_climate_target"}
            )
        point = matches[0]
        if not point["connected"]:
            raise HTTPException(
                status_code=409, detail={"error": "climate_unavailable"}
            )
        locator = runtime_data.locators.get(config_id, {}).get(device_id)
        if not point["target_settable"] or locator is None:
            raise HTTPException(
                status_code=409, detail={"error": "target_temperature_read_only"}
            )
        minimum = point["target_temperature_min_c"]
        maximum = point["target_temperature_max_c"]
        step = point["target_temperature_step_c"]
        if minimum is None or maximum is None or step is None or step <= 0:
            raise HTTPException(
                status_code=409, detail={"error": "target_constraints_unavailable"}
            )
        if not minimum <= value <= maximum:
            raise HTTPException(
                status_code=422, detail={"error": "target_temperature_out_of_range"}
            )
        if not _temperature_is_on_step(value, minimum, step):
            raise HTTPException(
                status_code=422, detail={"error": "target_temperature_off_step"}
            )
        client = runtime_data.clients.get(config_id)
        if client is None:
            raise HTTPException(
                status_code=409, detail={"error": "account_unavailable"}
            )
        try:
            gateway_id, management_point_id, target_path = locator
            quota = await client.set_target_temperature(
                gateway_id=gateway_id,
                management_point_id=management_point_id,
                path=target_path,
                value=value,
            )
        except OnectaError as exc:
            raise HTTPException(
                status_code=503, detail={"error": exc.category}
            ) from None
        point["target_temperature_c"] = value
        entry["quota"] = _quota_dict(quota)
        _publish_success(entry)
        append_runtime_event(
            "onecta.target_temperature.changed",
            entry,
            {"device_id": device_id, "target_temperature_c": value},
        )
        return {"device_id": device_id, "target_temperature_c": value}


async def poll_accounts() -> None:
    while True:
        await asyncio.sleep(2)
        now = time.monotonic()
        due = [
            entry
            for config_id in registry.ids()
            if (entry := registry.get(config_id)) is not None
            and float(entry.get("next_poll_at", 0)) <= now
        ]
        if due:
            await asyncio.gather(
                *(refresh_entry(entry) for entry in due), return_exceptions=True
            )


async def close_clients() -> None:
    for config_id in list(runtime_data.clients):
        await _discard_client(config_id)


def _register_automation_actions() -> None:
    async def refresh_handler(request):
        target = request.target if isinstance(request.target, dict) else {}
        config_id = str(request.config_id or target.get("config_id") or "")
        entry = get_entry_or_404(config_id)
        state = await refresh_entry(entry)
        if not state.get("connected"):
            raise RuntimeError("Daikin Onecta account is unavailable")
        return {"command": "refresh", "config_id": config_id, "state": state}

    async def set_temperature_handler(request):
        target = request.target if isinstance(request.target, dict) else {}
        args = request.args if isinstance(request.args, dict) else {}
        config_id = str(request.config_id or target.get("config_id") or "")
        device_id = str(request.device_id or target.get("device_id") or "")
        value = args.get("target_temperature_c")
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise HTTPException(
                status_code=422, detail={"error": "invalid_target_temperature"}
            )
        result = await set_target_temperature(config_id, device_id, float(value))
        return {"command": "set_target_temperature", "config_id": config_id, **result}

    automations.action("refresh", label=COMMANDS["refresh"]["description"])(
        refresh_handler
    )
    automations.action(
        "set_target_temperature",
        label=COMMANDS["set_target_temperature"]["description"],
    )(set_temperature_handler)


_register_automation_actions()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        if (entry := registry.get(config_id)) is not None:
            await refresh_entry(entry)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
