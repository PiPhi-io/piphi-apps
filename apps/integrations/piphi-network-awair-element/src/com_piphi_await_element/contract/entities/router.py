from fastapi import APIRouter

from com_piphi_await_element.lib.manifest import load_manifest
from com_piphi_await_element.lib.store import registry

router = APIRouter(tags=["entities"])


def _manifest_entity_capabilities(manifest: dict) -> list[str]:
    capabilities: set[str] = set()
    raw_entities = manifest.get("entities")
    entities: list = raw_entities if isinstance(raw_entities, list) else []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        raw_capabilities = entity.get("capabilities")
        entity_capabilities: list = raw_capabilities if isinstance(raw_capabilities, list) else []
        for capability_id in entity_capabilities:
            token = str(capability_id or "").strip()
            if token:
                capabilities.add(token)
    return sorted(capabilities)


@router.get('/entities')
async def get_entities():
    manifest = load_manifest()
    entity_capabilities = _manifest_entity_capabilities(manifest)
    entities: list[dict] = []

    for device_id in registry.ids():
        entry = registry.get(device_id) or {}
        latest_state = entry.get("latest_state") if isinstance(entry.get("latest_state"), dict) else {}
        name = "Awair Element"
        entities.append(
            {
                "id": str(entry.get("device_id") or device_id),
                "name": name,
                "config_id": str(entry.get("config_id") or "").strip() or None,
                "device_id": str(entry.get("device_id") or device_id),
                "device_class": "air-quality-sensor",
                "entity_type": "sensor",
                "capabilities": entity_capabilities,
                "dashboard": {
                    "default_widget": "stat",
                    "recommended_widgets": ["stat", "gauge", "line-chart"],
                },
                "latest_state": latest_state,
            }
        )

    return {
        "entities": entities,
        "capabilities": manifest.get("capabilities", {}),
        "commands": manifest.get("commands", {}),
    }
