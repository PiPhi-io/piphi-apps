from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .runtime_auth import authorize_runtime_request
from .settings import INTEGRATION_NAME
from .state import runtime


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.middleware("http")
    async def authorize_operational_routes(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if request.method == "POST" and request.url.path == "/config":
            expected_container_id, expected_token = runtime.auth.resolve()
            if not expected_container_id and not expected_token:
                return await call_next(request)
        try:
            authorize_runtime_request(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
