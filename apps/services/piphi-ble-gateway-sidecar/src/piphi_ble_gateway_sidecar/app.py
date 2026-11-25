from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME
from .runtime_auth import authorize_runtime_request


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.middleware("http")
    async def protect_runtime_api(request: Request, call_next):
        # Consumer routes enforce their own per-consumer Bearer capability.
        # Every other operational surface uses Core runtime authentication.
        if request.url.path != "/health" and not request.url.path.startswith("/v1/ble/"):
            try:
                authorize_runtime_request(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
