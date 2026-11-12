from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import build_entities_response

from piphi_network_thinqconnect.lib.manifest import load_manifest
from piphi_network_thinqconnect.lib.store import registry


router = APIRouter(tags=["entities"])


@router.get("/entities")
async def get_entities() -> dict:
    manifest = load_manifest()
    entities: list[dict] = []

    for device_id in registry.ids():
        entry = registry.get(device_id) or {}
        latest_state = entry.get("latest_state") if isinstance(entry.get("latest_state"), dict) else {}
        entity_name = (
            str(entry.get("alias") or "").strip()
            or str(latest_state.get("device_name") or "").strip()
            or str(entry.get("device_name") or "").strip()
            or str(device_id)
        )

        entities.append(
            {
                "id": str(entry.get("device_id") or device_id),
                "name": entity_name,
                "config_id": str(entry.get("config_id") or "").strip() or None,
                "device_id": str(entry.get("device_id") or device_id),
                "device_type": latest_state.get("device_type") or entry.get("device_type"),
                "device_class": latest_state.get("device_class"),
                "entity_type": latest_state.get("entity_type"),
                "capabilities": latest_state.get("capabilities") or ["refresh"],
                "available_commands": latest_state.get("available_commands") or [],
                "dashboard": latest_state.get("dashboard"),
                "metadata": {
                    "model": latest_state.get("model"),
                    "model_id": latest_state.get("model_id"),
                    "platform_type": latest_state.get("platform_type"),
                    "documented_capabilities": latest_state.get("documented_capabilities") or [],
                    "documented_commands": latest_state.get("documented_commands") or [],
                    "device_profile": latest_state.get("device_profile") or {},
                    "raw": latest_state.get("raw"),
                },
                "latest_state": latest_state,
            }
        )

    return build_entities_response(
        entities=entities,
        capabilities=manifest.get("capabilities", {}),
        commands=manifest.get("commands", {}),
    ).model_dump(exclude_none=True)
