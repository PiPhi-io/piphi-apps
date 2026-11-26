from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..mqtt_runtime import normalize_state_payload
from ..security import redact
from ..settings import (
    DEFAULT_SIDECAR_BASE_URL,
    INTEGRATION_ID,
    INTEGRATION_NAME,
    INTEGRATION_VERSION,
    PROJECT_DOMAIN,
    PROJECT_KIND,
    PROJECT_PRESET,
)
from ..sidecar_client import SidecarUnavailable, Zigbee2MqttSidecarClient
from ..state import mqtt_subscription_snapshot, registry, starter

router = APIRouter(tags=["runtime"])


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
    return redact({
        **state_payload,
        "summary": {
            "active_config_count": len(registry.ids()),
            "recent_event_count": len(registry.recent_events),
        },
        "entries": registry.entries,
        "state_snapshots": registry.state_snapshots,
        "mqtt_subscriptions": mqtt_subscription_snapshot(),
    })


async def _refresh_mqtt_state(*, dry_run: bool = False) -> None:
    for config_id, entry in list(registry.entries.items()):
        topic = str(entry.get("mqtt_topic") or "").strip()
        if not topic:
            continue
        try:
            if dry_run:
                messages: list[dict[str, Any]] = []
            else:
                result = await Zigbee2MqttSidecarClient(
                    base_url=str(
                        entry.get("sidecar_base_url") or DEFAULT_SIDECAR_BASE_URL
                    )
                ).mqtt_messages([topic])
                messages = result.get("messages") if isinstance(result.get("messages"), list) else []
        except SidecarUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        payload = messages[-1].get("payload") if messages and isinstance(messages[-1], dict) else {}
        if isinstance(payload, dict):
            registry.update_state(
                config_id,
                {
                    **normalize_state_payload(payload),
                    "mqtt_topic": topic,
                },
                device_id=str(entry.get("device_id") or config_id),
            )


starter.state.provide(_refresh_mqtt_state, source=INTEGRATION_ID)


@router.get("/contract")
async def contract() -> dict[str, Any]:
    return {
        "integration_id": INTEGRATION_ID,
        "name": INTEGRATION_NAME,
        "version": INTEGRATION_VERSION,
        "kind": PROJECT_KIND,
        "preset": PROJECT_PRESET,
        "domain": PROJECT_DOMAIN,
        "endpoints": ENDPOINTS,
        "required": REQUIRED_ENDPOINTS,
    }
