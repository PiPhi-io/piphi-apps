from __future__ import annotations

from fastapi import FastAPI

from .lifecycle import lifespan
from .routes import routers
from .state import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)
    for router in routers:
        app.include_router(router)
    return app
