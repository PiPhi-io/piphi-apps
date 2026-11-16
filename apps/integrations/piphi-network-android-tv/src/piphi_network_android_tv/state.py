from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .adb_sidecar_client import AdbSidecarClient
from .contract import CAPABILITIES, COMMANDS
from .device_sessions import DeviceSessionManager
from .remote_v2_adapter import AndroidTVRemoteV2Adapter
from .remote_v2_pairing import RemoteV2CredentialStore, RemoteV2PairingManager
from .runtime_service import AndroidTVRuntimeService
from .schemas import DeviceConfig, TransportType
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

# Upstream certificate generation respects the process umask. Set it before
# creating runtime stores so newly written credentials are never world-readable.
os.umask(0o077)

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

credential_store = RemoteV2CredentialStore(
    Path(os.getenv("PIPHI_ANDROID_TV_CREDENTIAL_DIR", "./data/android-tv-credentials"))
)
pairing_manager = RemoteV2PairingManager(credential_store)


def _receive_snapshot(config_id: str, snapshot) -> None:
    android_tv_service.receive_snapshot(config_id, snapshot)


session_manager = DeviceSessionManager(AndroidTVRemoteV2Adapter, _receive_snapshot)


def _credential_paths(config_id: str) -> tuple[Path, Path]:
    paths = credential_store.paths_for(config_id, create=True)
    return paths.certfile, paths.keyfile


android_tv_service = AndroidTVRuntimeService(
    registry=registry,
    sessions=session_manager,
    credentials=_credential_paths,
    adb=AdbSidecarClient(),
)


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    entry = {
        **identity,
        "alias": config.alias,
        "transport": config.transport.value,
        "config": config.model_dump(exclude={"host"}, mode="json"),
    }
    if config.transport is TransportType.REMOTE_V2:
        entry["host"] = config.host
    return entry


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
    await android_tv_service.configure(config, entry)
    configured = registry.get(str(entry["config_id"])) or entry
    append_runtime_event(
        "runtime.config.applied",
        configured,
        {"alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    entry = registry.get(config_id)
    if entry is None:
        return False
    await android_tv_service.remove(config_id)
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"alias": entry.get("alias")},
    )
    return True


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        async def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(request.device_id or target.get("device_id") or "demo-device")
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id) or {
                "device_id": device_id,
                "config_id": config_id,
            }
            if _command_name == "refresh":
                result = await android_tv_service.refresh(config_id)
            elif _command_name == "send_key":
                key = request.args.get("key") if isinstance(request.args, dict) else None
                if not isinstance(key, str) or not key.strip():
                    raise HTTPException(status_code=400, detail="send_key requires a key")
                await android_tv_service.send_key(config_id, key)
                result = {"accepted": True, "key": key.strip().upper()}
            else:
                raise HTTPException(status_code=400, detail="Unsupported command")
            event = append_runtime_event(
                "runtime.command.received",
                entry,
                {
                    "command": _command_name,
                    "device_id": device_id,
                    "entity_id": request.entity_id,
                    "args": request.args,
                    "target": target,
                },
            )
            return {
                "event": event,
                "command": _command_name,
                "device_id": device_id,
                "config_id": config_id,
                "target": target,
                "params": request.args,
                "result": result,
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


_register_automation_actions()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await android_tv_service.refresh(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
