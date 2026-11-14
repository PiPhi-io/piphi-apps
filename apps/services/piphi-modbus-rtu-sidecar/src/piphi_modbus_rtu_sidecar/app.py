from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)
    @app.middleware("http")
    async def protect_parent_api(request: Request, call_next):
        protected = (
            request.url.path == "/command"
            or request.url.path in {"/config", "/config/sync", "/deconfigure"}
            or request.url.path.startswith("/deconfigure/")
            or request.url.path.startswith("/v1/modbus/")
        )
        if protected:
            from .authorization import authorize_sidecar_request

            try:
                authorize_sidecar_request(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
