from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from piphi_runtime_kit_python import RuntimeStateService

from piphi_network_thinqconnect.contract.config.routes import (
    resolve_entry_id,
    trigger_refresh,
)
from piphi_network_thinqconnect.lib.runtime_auth import authorize_runtime_request
from piphi_network_thinqconnect.lib.store import (
    get_primary_device,
    registry,
)

router = APIRouter(tags=["state"])
state_service = RuntimeStateService(registry)


async def _refresh_all_devices() -> None:
    for configured_id in registry.ids():
        await trigger_refresh(configured_id)


state_service.provide(_refresh_all_devices, source="LG ThinQ Connect API")


def _identity_addressed_entry(entry_id: str) -> tuple[str, dict[str, Any]] | None:
    snapshot = registry.state_snapshots.get(entry_id)
    configured = registry.get(entry_id)
    if not isinstance(snapshot, dict) or not isinstance(configured, dict):
        return None
    state = snapshot.get("state")
    if not isinstance(state, dict):
        return None
    metrics = state.get("metrics")
    latest_state = dict(metrics) if isinstance(metrics, dict) else {}
    latest_state.update(
        {
            key: value
            for key, value in state.items()
            if key != "metrics" and isinstance(value, (str, int, float, bool, type(None)))
        }
    )
    config_id = str(configured.get("config_id") or entry_id)
    device_id = str(configured.get("device_id") or snapshot.get("device_id") or entry_id)
    latest_state["device_id"] = device_id
    return config_id, {
        "config_id": config_id,
        "device_id": device_id,
        "latest_state": latest_state,
        "last_updated": snapshot.get("last_updated"),
    }


@router.get("/state")
async def get_state(
    request: Request,
    device_id: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    refresh_request_id: str | None = Query(default=None),
) -> dict:
    authorize_runtime_request(request)
    if refresh_request_id is not None:
        try:
            return await state_service.response(
                refresh=refresh,
                refresh_request_id=refresh_request_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if device_id is None:
        primary_device = get_primary_device()
        if primary_device is None:
            raise HTTPException(status_code=404, detail="No configured device found")

        if len(registry.ids()) > 1:
            failures: dict[str, dict[str, Any]] = {}
            if refresh:
                for configured_id in registry.ids():
                    try:
                        await trigger_refresh(configured_id)
                    except HTTPException as exc:
                        configured = registry.get(configured_id) or {}
                        config_id = str(configured.get("config_id") or configured_id)
                        failures[config_id] = {
                            "config_id": config_id,
                            "device_id": str(
                                configured.get("device_id") or configured_id
                            ),
                            "status_code": exc.status_code,
                            "available": False,
                        }
            entries = dict(
                entry
                for configured_id in registry.ids()
                if str((registry.get(configured_id) or {}).get("config_id") or configured_id)
                not in failures
                and (entry := _identity_addressed_entry(configured_id)) is not None
            )
            return {
                "entries": entries,
                "failures": failures,
                "state_scope": "identity-addressed",
            }
        device_id = primary_device["device_id"]

    entry_id = resolve_entry_id(device_id)
    if entry_id is None:
        raise HTTPException(status_code=404, detail=f"No state available for device '{device_id}'")

    if refresh or (
        entry_id not in registry.state_snapshots and registry.get(entry_id) is not None
    ):
        await trigger_refresh(entry_id)

    entry = _identity_addressed_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No state available for device '{device_id}'")
    identity, payload = entry
    return {
        "entries": {identity: payload},
        "state_scope": "identity-addressed",
    }
