from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .runtime_auth import authorize_runtime_request
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.middleware("http")
    async def protect_runtime_api(request: Request, call_next):
        # Health is the sole unauthenticated liveness surface. Configuration
        # bootstrap is authenticated by its route because it may establish the
        # runtime identity used by all subsequent requests.
        if request.url.path not in {"/health", "/config", "/config/sync"}:
            try:
                authorize_runtime_request(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code, content={"detail": exc.detail}
                )
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
