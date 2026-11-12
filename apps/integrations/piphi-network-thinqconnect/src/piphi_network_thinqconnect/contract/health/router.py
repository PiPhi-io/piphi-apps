from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    RuntimeDiagnosticsResponse,
    RuntimeHealthResponse,
    build_runtime_diagnostics_response,
    build_runtime_health_response,
)

from piphi_network_thinqconnect.lib.manifest import load_manifest
from piphi_network_thinqconnect.lib.store import list_pending_background_tasks, runtime_context, registry


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_report() -> RuntimeHealthResponse:
    manifest = load_manifest()
    return build_runtime_health_response(
        runtime_context,
        integration={
            "id": manifest["id"],
            "name": manifest["name"],
            "version": manifest["version"],
        },
        metadata={
            "devices_configured": len(registry.entries),
            "devices_with_state": len(registry.state_snapshots),
            "background_tasks": len(list_pending_background_tasks()),
        },
    )


@router.get("/diagnostics")
async def diagnostics_report() -> RuntimeDiagnosticsResponse:
    manifest = load_manifest()
    return build_runtime_diagnostics_response(
        runtime_context,
        integration={
            "id": manifest["id"],
            "name": manifest["name"],
            "version": manifest["version"],
        },
        diagnostics={
            "configured_device_ids": sorted(registry.entries.keys()),
            "devices_with_state": sorted(registry.state_snapshots.keys()),
        },
    )
