from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.middleware("http")
    async def require_runtime_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        expected = os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
        allow_unauthenticated = (
            os.getenv("PIPHI_ALLOW_UNAUTHENTICATED", "").lower() == "true"
        )
        if not expected and not allow_unauthenticated:
            return JSONResponse(
                status_code=503,
                content={"detail": "runtime authentication is not configured"},
            )
        if expected:
            provided = request.headers.get("X-PiPhi-Integration-Token", "")
            if not hmac.compare_digest(provided, expected):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid runtime token"},
                )
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    return app
