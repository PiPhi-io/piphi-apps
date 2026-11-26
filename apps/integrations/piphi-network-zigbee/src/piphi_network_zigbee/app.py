from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .security import authorize_request, install_log_scrubbing
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    install_log_scrubbing()
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.middleware("http")
    async def protect_runtime(request: Request, call_next):
        if request.url.path != "/health":
            try:
                authorize_request(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
