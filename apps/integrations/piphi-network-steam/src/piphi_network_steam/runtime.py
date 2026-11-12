from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
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
from pydantic import BaseModel, Field, SecretStr, field_validator

from .steam_client import (
    SteamAPIError,
    SteamAuthenticationError,
    SteamCredentials,
    SteamRateLimitError,
    SteamSnapshot,
    SteamWebAPIClient,
)

INTEGRATION_ID = "piphi-network-steam"
INTEGRATION_NAME = "Steam"
INTEGRATION_VERSION = "0.1.0"
DEFAULT_POLL_INTERVAL_SECONDS = 300
logger = logging.getLogger(__name__)

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
    core_base_url=resolve_core_base_url("http://127.0.0.1:31419"),
)
runtime = starter.runtime
registry = starter.registry
telemetry_client = starter.telemetry_client
event_client = starter.event_client
config_sync = starter.config_sync
steam_client = SteamWebAPIClient()
router = APIRouter()
automation_registry = AutomationRegistry()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await _read_and_store(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
poll_tasks: dict[str, asyncio.Task[Any]] = {}
poll_status: dict[str, dict[str, Any]] = {}


class SteamConfig(RuntimeConfig):
    steam_id: str
    web_api_key: SecretStr
    display_name: str | None = None
    poll_interval_seconds: int = Field(
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        ge=60,
        le=86400,
    )

    @field_validator("steam_id")
    @classmethod
    def validate_steam_id(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 17 or not normalized.isdigit():
            raise ValueError("steam_id must be a 17-digit SteamID64")
        return normalized


class DeconfigurePayload(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


def set_steam_client(client: SteamWebAPIClient) -> None:
    global steam_client
    steam_client = client


def _config_id(config: SteamConfig) -> str:
    return str(getattr(config, "config_id", None) or config.id)


def _credentials_from_config(config: SteamConfig) -> SteamCredentials:
    return SteamCredentials(
        steam_id=config.steam_id,
        web_api_key=config.web_api_key.get_secret_value(),
    )


def _credentials_from_entry(entry: dict[str, Any]) -> SteamCredentials:
    return SteamCredentials(
        steam_id=str(entry["steam_id"]),
        web_api_key=str(entry["web_api_key"]),
    )


def _public_device(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_id": entry["config_id"],
        "device_id": entry["steam_id"],
        "integration_id": INTEGRATION_ID,
        "name": entry.get("display_name") or f"Steam {entry['steam_id']}",
    }


def _raise_http_for_steam_error(exc: SteamAPIError) -> None:
    if isinstance(exc, SteamAuthenticationError):
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if isinstance(exc, SteamRateLimitError):
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def _schedule_event(
    *,
    event_type: str,
    entry: dict[str, Any],
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> None:
    device = _public_device(entry)
    registry.append_event(
        build_local_event_record(
            event_type=event_type,
            device=device,
            payload=payload,
            source=INTEGRATION_ID,
            severity=severity,
        )
    )
    schedule_event_delivery(
        process_state=runtime.process_state,
        event_client=event_client,
        auth_context=runtime.auth,
        event_type=event_type,
        device=device,
        payload=payload,
        source=INTEGRATION_ID,
        severity=severity,
    )


def _transition_events(
    entry: dict[str, Any],
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> None:
    if previous is None:
        return
    before_game = previous.get("current_game_name")
    after_game = current.get("current_game_name")
    if not before_game and after_game:
        _schedule_event(
            event_type="steam.game.started",
            entry=entry,
            payload={"game_name": after_game, "app_id": current.get("current_game_app_id")},
        )
    elif before_game and not after_game:
        _schedule_event(
            event_type="steam.game.stopped",
            entry=entry,
            payload={"game_name": before_game},
        )
    elif before_game and after_game and before_game != after_game:
        _schedule_event(
            event_type="steam.game.changed",
            entry=entry,
            payload={"from": before_game, "to": after_game},
        )
    if previous.get("persona_state") != current.get("persona_state"):
        _schedule_event(
            event_type="steam.persona.changed",
            entry=entry,
            payload={
                "from": previous.get("persona_state"),
                "to": current.get("persona_state"),
            },
        )


async def _read_and_store(config_id: str) -> SteamSnapshot:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    poll_status.setdefault(config_id, {})["last_poll_started"] = asyncio.get_running_loop().time()
    previous = registry.state_snapshots.get(config_id, {}).get("state")
    snapshot = await steam_client.fetch_snapshot(_credentials_from_entry(entry))
    state = {
        **snapshot.state,
        "connected": True,
        "display_name": entry.get("display_name") or snapshot.state["persona_name"],
        "last_error": None,
        "sampled_at": snapshot.sampled_at,
    }
    registry.update_state(config_id, state)
    _transition_events(entry, previous, state)
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry_client,
        auth_context=runtime.auth,
        config_id=config_id,
        device_id=str(entry["steam_id"]),
        metrics=snapshot.metrics,
        container_id=entry.get("container_id"),
        timestamp=snapshot.sampled_at,
    )
    poll_status[config_id].update(
        {"last_poll_succeeded": snapshot.sampled_at, "last_poll_error": None}
    )
    return snapshot


async def _poll_config(config_id: str, interval_seconds: int) -> None:
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await _read_and_store(config_id)
        except asyncio.CancelledError:
            raise
        except (SteamAPIError, HTTPException) as exc:
            entry = registry.get(config_id)
            if entry is not None:
                old = registry.state_snapshots.get(config_id, {}).get("state", {})
                registry.update_state(
                    config_id,
                    {**old, "connected": False, "last_error": str(exc)},
                )
                poll_status.setdefault(config_id, {})["last_poll_error"] = str(exc)
                _schedule_event(
                    event_type="steam.poll.failed",
                    entry=entry,
                    payload={"error": str(exc)},
                    severity="warning",
                )


async def apply_config(config: SteamConfig) -> dict[str, Any]:
    config_id = _config_id(config)
    await remove_config(config_id)
    try:
        initial = await steam_client.fetch_snapshot(_credentials_from_config(config))
    except SteamAPIError as exc:
        _raise_http_for_steam_error(exc)
    entry = {
        "config_id": config_id,
        "container_id": getattr(config, "container_id", None),
        "steam_id": config.steam_id,
        "web_api_key": config.web_api_key.get_secret_value(),
        "display_name": config.display_name or initial.state["persona_name"],
        "poll_interval_seconds": config.poll_interval_seconds,
    }
    registry.set(config_id, entry)
    state = {
        **initial.state,
        "connected": True,
        "display_name": entry["display_name"],
        "last_error": None,
        "sampled_at": initial.sampled_at,
    }
    registry.update_state(config_id, state)
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry_client,
        auth_context=runtime.auth,
        config_id=config_id,
        device_id=config.steam_id,
        metrics=initial.metrics,
        container_id=entry.get("container_id"),
        timestamp=initial.sampled_at,
    )
    poll_status[config_id] = {"last_poll_succeeded": initial.sampled_at}
    poll_tasks[config_id] = create_tracked_task(
        _poll_config(config_id, config.poll_interval_seconds),
        process_state=runtime.process_state,
    )
    _schedule_event(event_type="device.configured", entry=entry)
    return entry


async def remove_config(config_id: str) -> bool:
    task = poll_tasks.pop(config_id, None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    entry = registry.remove(config_id)
    poll_status.pop(config_id, None)
    if entry is None:
        return False
    _schedule_event(event_type="device.deconfigured", entry=entry)
    return True


async def reset_runtime_state() -> None:
    for config_id in list(poll_tasks):
        await remove_config(config_id)
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime.process_state.background_tasks.clear()


async def _refresh(action: AutomationActionRequest) -> AutomationActionResult:
    config_id = str(action.config_id or "").strip()
    try:
        snapshot = await _read_and_store(config_id)
    except (SteamAPIError, HTTPException) as exc:
        status = exc.status_code if isinstance(exc, HTTPException) else 503
        return AutomationActionResult.failure(
            str(getattr(exc, "detail", exc)),
            retryable=status in {429, 502, 503},
            metadata={"status_code": status},
        )
    return AutomationActionResult.success(
        {"status": "ok", "config_id": config_id, "sampled_at": snapshot.sampled_at}
    )


automation_registry.action("refresh")(_refresh)


async def _extract_inputs(
    request: Request,
    payload: IntegrationDiscoveryRequest | None,
) -> dict[str, Any]:
    if payload is not None and isinstance(payload.inputs, dict) and payload.inputs:
        return dict(payload.inputs)
    try:
        raw = await request.json()
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return dict(raw.get("inputs") or raw)


def _capabilities(state: dict[str, Any]) -> list[str]:
    keys = (
        "connected",
        "is_online",
        "is_in_game",
        "persona_state",
        "current_game_name",
        "owned_game_count",
        "recent_game_count",
        "total_playtime_minutes",
        "recent_playtime_minutes",
        "library_visible",
        "recent_games_visible",
    )
    return [key for key in keys if key in state] + ["refresh"]


def _entities() -> list[dict[str, Any]]:
    result = []
    for config_id, entry in registry.entries.items():
        state = registry.state_snapshots.get(config_id, {}).get("state", {})
        result.append(
            {
                "id": f"account:{config_id}",
                "name": entry.get("display_name") or f"Steam {entry['steam_id']}",
                "config_id": config_id,
                "device_id": entry["steam_id"],
                "device_class": "gaming_account",
                "entity_type": "account",
                "capabilities": _capabilities(state),
                "available_commands": [
                    {
                        "id": "refresh",
                        "label": "Refresh",
                        "kind": "action",
                        "description": "Fetch the latest Steam activity now.",
                    }
                ],
                "dashboard": {
                    "allowed_widgets": ["external-widget", "stat", "text"],
                    "default_widget": "external-widget",
                    "recommended_widgets": ["external-widget"],
                },
                "metadata": {"steam_id": entry["steam_id"]},
            }
        )
    return result


@router.get("/health")
async def health() -> RuntimeHealthResponse:
    return starter.health_response(
        metadata={"active_configs": len(registry.ids()), "poll_tasks": len(poll_tasks)}
    )


@router.get("/diagnostics")
async def diagnostics() -> RuntimeDiagnosticsResponse:
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "poll_status": poll_status,
            "state_snapshots": registry.state_snapshots,
            "recent_event_count": len(registry.recent_events),
        }
    )


@router.get("/ui")
@router.get("/ui-config")
async def ui_config() -> dict[str, Any]:
    return {
        "schema": {
            "title": "Steam Setup",
            "description": "Connect one Steam account with its SteamID64 and Web API key.",
            "type": "object",
            "required": ["steam_id", "web_api_key"],
            "properties": {
                "steam_id": {
                    "type": "string",
                    "title": "SteamID64",
                    "pattern": "^[0-9]{17}$",
                },
                "web_api_key": {
                    "type": "string",
                    "title": "Steam Web API key",
                    "description": "Kept secret and used only for Steam Web API requests.",
                },
                "display_name": {"type": "string", "title": "Display name"},
                "poll_interval_seconds": {
                    "type": "integer",
                    "title": "Poll interval (seconds)",
                    "default": DEFAULT_POLL_INTERVAL_SECONDS,
                    "minimum": 60,
                },
            },
        },
        "uiSchema": {"web_api_key": {"ui:widget": "password"}},
    }


@router.get("/discover", response_model=IntegrationDiscoveryResponse)
@router.post("/discover", response_model=IntegrationDiscoveryResponse)
async def discover(
    request: Request,
    payload: IntegrationDiscoveryRequest | None = None,
) -> IntegrationDiscoveryResponse:
    inputs = await _extract_inputs(request, payload)
    try:
        config = SteamConfig(
            id="discovery",
            steam_id=str(inputs.get("steam_id") or ""),
            web_api_key=SecretStr(str(inputs.get("web_api_key") or "")),
        )
        snapshot = await steam_client.fetch_snapshot(_credentials_from_config(config))
    except SteamAPIError as exc:
        _raise_http_for_steam_error(exc)
    return build_discovery_response(
        [
            {
                "id": config.steam_id,
                "name": snapshot.state["persona_name"],
                "device_id": config.steam_id,
                "device_class": "gaming_account",
                "metadata": {
                    "profile_url": snapshot.state.get("profile_url"),
                    "library_visible": snapshot.state["library_visible"],
                },
            }
        ]
    )


@router.post("/config")
async def config(payload: SteamConfig, request: Request) -> RuntimeConfigApplyResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    entry = await apply_config(payload)
    return build_config_apply_response(
        config_id=_config_id(payload),
        container_id=entry.get("container_id"),
        metadata={"steam_id": entry["steam_id"]},
    )


async def apply_runtime_config_snapshot(
    payload: RuntimeConfigSnapshot,
) -> RuntimeConfigSyncResponse:
    typed = payload.model_copy(
        update={
            "configs": validate_typed_configs(
                [c.model_dump() if hasattr(c, "model_dump") else c for c in payload.configs],
                SteamConfig,
            )
        }
    )
    return await config_sync.apply_snapshot(
        snapshot=typed,
        active_config_ids=registry.ids(),
        apply_config=apply_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


@router.post("/configs/sync")
@router.post("/config/sync")
async def configs_sync(
    payload: RuntimeConfigSnapshot,
    request: Request,
) -> RuntimeConfigSyncResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    return await apply_runtime_config_snapshot(payload)


@router.post("/deconfigure")
async def deconfigure(
    payload: DeconfigurePayload,
    request: Request,
) -> RuntimeConfigRemoveResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    config_id = str(payload.config.get("config_id") or payload.config.get("id") or "")
    if not config_id:
        raise HTTPException(status_code=400, detail="config_id is required")
    return build_config_remove_response(
        config_id=config_id,
        removed=await remove_config(config_id),
    )


@router.get("/entities")
async def entities() -> dict[str, Any]:
    return starter.entities_response(entities=_entities()).model_dump()


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
    return {
        **state_payload,
        "state": registry.state_snapshots,
    }


@router.get("/events", response_model=IntegrationEventListResponse)
async def events() -> IntegrationEventListResponse:
    return build_event_list_response(registry.recent_events)


@router.post("/command")
async def command(payload: IntegrationCommandRequest, request: Request) -> dict[str, Any]:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    target = payload.target if isinstance(payload.target, dict) else {}
    config_id = str(
        payload.config_id or payload.args.get("config_id") or target.get("config_id") or ""
    )
    if not config_id and payload.entity_id and payload.entity_id.startswith("account:"):
        config_id = payload.entity_id.split(":", 1)[1]
    device_id = payload.device_id or target.get("device_id")
    if not config_id and device_id:
        for candidate_id, entry in registry.entries.items():
            if str(entry["steam_id"]) == str(device_id):
                config_id = candidate_id
                break
    if not config_id:
        raise HTTPException(
            status_code=400, detail="config_id, entity_id, or device_id is required"
        )
    if payload.command != "refresh":
        raise HTTPException(status_code=400, detail=f"Unsupported command: {payload.command}")
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        {
            **payload.model_dump(mode="python"),
            "args": payload.params or payload.args,
            "config_id": config_id,
            "device_id": device_id,
        },
    )
    if not result.ok:
        raise HTTPException(
            status_code=int(result.metadata.get("status_code") or 503),
            detail=result.error,
        )
    return result.model_dump(mode="json")
