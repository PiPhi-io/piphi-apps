from __future__ import annotations

from .bridge import router as bridge_router
from .commands import router as command_router
from .config import router as config_router
from .discovery import router as discovery_router
from .entities import router as entity_router
from .events import router as event_router
from .health import router as health_router
from .runtime import router as runtime_router
from .telemetry import router as telemetry_router

routers = [
    health_router,
    bridge_router,
    discovery_router,
    config_router,
    runtime_router,
    entity_router,
    event_router,
    telemetry_router,
    command_router,
]
