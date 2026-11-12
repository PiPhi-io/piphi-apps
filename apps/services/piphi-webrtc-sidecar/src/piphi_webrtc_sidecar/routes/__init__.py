from __future__ import annotations

from .health import router as health_router
from .media_sidecar import router as media_sidecar_router
from .runtime import router as runtime_router

routers = [
    health_router,
    media_sidecar_router,
    runtime_router,
]
