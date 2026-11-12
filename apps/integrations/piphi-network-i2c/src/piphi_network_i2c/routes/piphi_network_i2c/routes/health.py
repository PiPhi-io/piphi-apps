from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import RuntimeDiagnosticsResponse, RuntimeHealthResponse

from ..state import diagnostics_payload, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health", response_model=RuntimeHealthResponse)
async def health() -> RuntimeHealthResponse:
    return starter.health_response(metadata={"active_configs": len(registry.ids())})


@router.get("/diagnostics", response_model=RuntimeDiagnosticsResponse)
async def diagnostics() -> RuntimeDiagnosticsResponse:
    return starter.diagnostics_response(diagnostics=diagnostics_payload())
