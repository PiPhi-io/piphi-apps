from .commands import router as commands_router
from .config import router as config_router
from .entities import router as entities_router
from .events import router as events_router
from .health import router as health_router
from .runtime import router as runtime_router

routers = [
    health_router,
    config_router,
    entities_router,
    events_router,
    runtime_router,
    commands_router,
]
