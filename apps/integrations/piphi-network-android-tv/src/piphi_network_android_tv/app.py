from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .runtime_auth import authorize_runtime_request
from .security import install_log_scrubbing
from .settings import INTEGRATION_NAME
from .state import runtime


def create_app() -> FastAPI:
    install_log_scrubbing()
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def sanitized_validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"type": item.get("type"), "loc": list(item.get("loc") or []), "msg": item.get("msg")}
                    for item in exc.errors()
                ]
            },
        )

    @app.middleware("http")
    async def runtime_auth_boundary(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        try:
            authorize_runtime_request(
                request,
                runtime_context=runtime,
                allow_bootstrap=request.url.path in {"/config", "/config/sync"},
            )
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
