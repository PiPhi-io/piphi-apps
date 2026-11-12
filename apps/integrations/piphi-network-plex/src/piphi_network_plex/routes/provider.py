from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from ..schemas import ProviderResolveRequest
from ..state import plex_service

router = APIRouter(prefix="/provider", tags=["media-provider"])


@router.get("/instances")
async def instances(config_id: str = ""):
    values = plex_service.instances(config_id or None)
    return {"provider": "plex", "instances": values, "total": len(values)}


@router.get("/{instance_id}/collections")
async def collections(instance_id: str):
    values = await plex_service.collections(instance_id)
    return {"provider": "plex", "provider_instance_id": instance_id, "collections": values, "total": len(values)}


@router.get("/{instance_id}/items")
async def items(instance_id: str, collection_id: str = "", hub: str = "", q: str = "", limit: int = Query(default=50, ge=1, le=200)):
    values = await plex_service.items(instance_id, collection_id=collection_id, hub=hub, query=q, limit=limit)
    return {"provider": "plex", "provider_instance_id": instance_id, "items": values, "total": len(values), "next_cursor": None}


@router.post("/{instance_id}/resolve")
async def resolve(instance_id: str, payload: ProviderResolveRequest):
    item = await plex_service.resolve(instance_id, payload.item_id)
    return {"provider": "plex", "provider_instance_id": instance_id, "item": item}


@router.post("/{instance_id}/actions")
async def action(instance_id: str, payload: dict):
    return await plex_service.action(
        instance_id,
        str(payload.get("action") or ""),
        item_id=str(payload.get("item_id") or ""),
        value=payload.get("value"),
        collection_id=str(payload.get("collection_id") or ""),
    )


@router.get("/{instance_id}/asset")
async def asset(instance_id: str, path: str):
    content, content_type = await plex_service.asset(instance_id, path)
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})
