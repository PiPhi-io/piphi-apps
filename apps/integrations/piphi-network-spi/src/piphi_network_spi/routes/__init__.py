from __future__ import annotations

from .commands import router as command_router
from .config import router as config_router
from .discovery import router as discovery_router
from .entities import router as entities_router
from .events import router as events_router
from .health import router as health_router
from .runtime import router as runtime_router

routers = [
    health_router,
    discovery_router,
    config_router,
    runtime_router,
    entities_router,
    events_router,
    command_router,
]
