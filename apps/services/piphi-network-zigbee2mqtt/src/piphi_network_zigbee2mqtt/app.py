from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.middleware("http")
    async def protect_sidecar_api(request: Request, call_next):
        path = request.url.path
        protected = (
            path.startswith(("/v1/", "/deconfigure/", "/events/", "/telemetry/"))
            or path
            in {
                "/command",
                "/config",
                "/config/sync",
                "/deconfigure",
                "/state",
                "/diagnostics",
                "/entities",
                "/events",
                "/telemetry",
            }
        )
        if protected:
            from .authorization import authorize_sidecar_request

            try:
                authorize_sidecar_request(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                )
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
