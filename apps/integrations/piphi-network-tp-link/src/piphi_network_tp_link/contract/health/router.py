from fastapi import APIRouter
from piphi_runtime_kit_python import (
    RuntimeDiagnosticsResponse,
    RuntimeHealthResponse,
    build_runtime_diagnostics_response,
    build_runtime_health_response,
)

from piphi_network_tp_link.lib.manifest import load_manifest
from piphi_network_tp_link.lib.store import get_runtime_context, registry
from piphi_network_tp_link.lib.security import diagnostic_id

router = APIRouter(tags=["health"])
runtime_context = get_runtime_context()


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
            "configured_devices": sorted(diagnostic_id(value) for value in registry.entries),
            "devices_with_state": sorted(diagnostic_id(value) for value in registry.state_snapshots),
        },
    )
