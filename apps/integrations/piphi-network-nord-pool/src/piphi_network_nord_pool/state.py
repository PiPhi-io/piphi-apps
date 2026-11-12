from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from time import monotonic
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
from .market_client import MarketDataError, fetch_prices
from .schemas import DeviceConfig
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
_next_poll: dict[str, float] = {}


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "market_area": config.market_area,
        "alias": config.alias,
        "currency": config.currency,
        "poll_interval_seconds": config.poll_interval_seconds,
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
    config_id = entry["config_id"]
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        {
            "connected": False,
            "market_area": config.market_area,
        },
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"market_area": config.market_area},
    )
    _next_poll.pop(config_id, None)


async def remove_config(config_id: str) -> bool:
    _next_poll.pop(config_id, None)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"market_area": entry.get("market_area")},
    )
    return True


async def refresh_config(config_id: str) -> dict[str, Any]:
    """Read a current market interval and publish only validated state."""
    entry = get_entry_or_404(config_id)
    try:
        prices = await fetch_prices(
            area=entry["market_area"],
            currency=entry["currency"],
            now=datetime.now(timezone.utc),
        )
    except MarketDataError:
        previous = registry.state_snapshots.get(config_id, {}).get("state", {})
        registry.update_state(
            config_id,
            {**previous, "connected": False},
            device_id=entry["device_id"],
        )
        raise
    latest = {
        "connected": True,
        "market_area": prices["market_area"],
        "current_price_per_kwh": prices["current_price_per_kwh"],
        "next_price_per_kwh": prices["next_price_per_kwh"],
        "price_unit": prices["price_unit"],
    }
    registry.update_state(config_id, latest, device_id=entry["device_id"])
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=entry["config_id"],
        device_id=entry["device_id"],
        container_id=entry.get("container_id"),
        metrics={key: value for key, value in latest.items() if value is not None},
        units={
            "current_price_per_kwh": prices["price_unit"],
            "next_price_per_kwh": prices["price_unit"],
        },
    )
    return latest


async def market_poll_loop() -> None:
    """Poll configured areas; failures retry sooner while retaining last good price."""
    while True:
        for config_id in registry.ids():
            entry = registry.get(config_id)
            if entry is None or monotonic() < _next_poll.get(config_id, 0):
                continue
            try:
                await refresh_config(config_id)
            except MarketDataError:
                _next_poll[config_id] = monotonic() + 60
            else:
                _next_poll[config_id] = monotonic() + entry["poll_interval_seconds"]
        await asyncio.sleep(1)


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(request.device_id or target.get("device_id") or "demo-device")
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id) or {
                "device_id": device_id,
                "config_id": config_id,
            }
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
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


_register_automation_actions()
async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await refresh_config(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
