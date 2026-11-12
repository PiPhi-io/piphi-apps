from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    assert_behaviors_contract,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .contract import CAPABILITIES, COMMANDS
from .schemas import DeviceConfig
from .service import SolarEdgeRuntimeService
from .solaredge_client import (
    SolarEdgeAuthenticationError,
    SolarEdgeClientError,
    SolarEdgeRateLimitError,
    SolarEdgeRequestError,
    SolarEdgeTransientError,
)
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
solaredge_service = SolarEdgeRuntimeService(
    registry=registry,
    runtime=runtime,
    telemetry=telemetry,
)

_behavior_candidates = (
    Path(__file__).with_name("behaviors.json"),
    Path(__file__).resolve().parents[1] / "behaviors.json",
)
BEHAVIORS = json.loads(next(path for path in _behavior_candidates if path.exists()).read_text())

# Core projects telemetry from this runtime into this canonical event. Declaring
# it here exposes the event schema to the automation SDK without emitting a
# duplicate event alongside every telemetry delivery.
automations.event(
    "device.state_changed",
    label="SolarEdge site state changed",
    data_schema={
        "capabilities": {"type": "array"},
        "changed_metrics": {"type": "array"},
    },
)


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "site_id": config.site_id,
        "alias": config.alias,
        "config": {
            "site_id": config.site_id,
            "alias": config.alias,
            "poll_interval_seconds": config.poll_interval_seconds,
            "summary_interval_seconds": config.summary_interval_seconds,
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
        await solaredge_service.configure(config, entry)
    except Exception:
        if previous is None:
            registry.remove(config_id)
        else:
            registry.set(config_id, previous)
        raise
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"site_id": config.site_id, "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    await solaredge_service.remove(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"site_id": entry.get("site_id"), "alias": entry.get("alias")},
    )
    return True


@automations.action(
    "refresh",
    label="Refresh SolarEdge power flow and energy totals",
    parameter_schema={},
    result_schema={"state": {"type": "object"}},
)
async def refresh_automation(
    request: AutomationActionRequest,
) -> AutomationActionResult:
    request_target = getattr(request, "target", None)
    target = request_target if isinstance(request_target, dict) else {}
    device_id = str(request.device_id or target.get("device_id") or "solaredge-site")
    config_id = str(request.config_id or target.get("config_id") or device_id)
    active_config_id = solaredge_service.active_config_id
    if active_config_id is None:
        return AutomationActionResult.failure(
            "SolarEdge is not configured", retryable=False
        )
    if config_id != active_config_id:
        return AutomationActionResult.failure(
            f"Automation target {config_id!r} is not the active SolarEdge config",
            retryable=False,
        )

    entry = registry.get(config_id) or {
        "device_id": device_id,
        "config_id": config_id,
    }
    append_runtime_event(
        "runtime.command.received",
        entry,
        {
            "command": request.command,
            "device_id": device_id,
            "entity_id": request.entity_id,
            "args": request.args,
            "target": target,
        },
    )
    try:
        state = await solaredge_service.refresh(force_summary=True)
    except (SolarEdgeRateLimitError, SolarEdgeTransientError) as exc:
        return AutomationActionResult.failure(
            str(exc), retryable=True, metadata={"service": "solaredge"}
        )
    except (SolarEdgeAuthenticationError, SolarEdgeRequestError) as exc:
        return AutomationActionResult.failure(
            str(exc), retryable=False, metadata={"service": "solaredge"}
        )
    except SolarEdgeClientError as exc:
        return AutomationActionResult.failure(
            str(exc), retryable=True, metadata={"service": "solaredge"}
        )

    return AutomationActionResult.success(
        state=state,
        command=request.command,
        device_id=device_id,
        config_id=config_id,
        target=target,
        params=request.args,
    )


assert_behaviors_contract(BEHAVIORS, automations)


async def _refresh_all_state() -> None:
    if solaredge_service.active_config_id is not None:
        await solaredge_service.refresh(force_summary=True)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
