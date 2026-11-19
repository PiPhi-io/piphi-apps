from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .authorization import authorize_sidecar_request
from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.middleware("http")
    async def protect_operational_routes(request: Request, call_next):
        response = None
        if request.url.path != "/health":
            try:
                authorize_sidecar_request(request)
            except HTTPException as exc:
                response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        if response is None:
            response = await call_next(request)
        if request.url.path.startswith(("/v1/camera-media/sessions", "/v1/analysis-media")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    for router in routers:
        app.include_router(router)
    return app
