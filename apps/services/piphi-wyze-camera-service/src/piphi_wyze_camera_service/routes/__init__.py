from __future__ import annotations

from .health import router as health_router
from .service import router as service_router

routers = [health_router, service_router]
