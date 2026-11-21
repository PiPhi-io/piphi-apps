from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .lifespan import lifespan
from .runtime import router


def create_app() -> FastAPI:
    application = FastAPI(title="PiPhi Network Steam", lifespan=lifespan)

    @application.middleware("http")
    async def require_runtime_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        expected = os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
        if not expected and os.getenv("PIPHI_ALLOW_UNAUTHENTICATED", "").lower() != "true":
            return JSONResponse(
                status_code=503,
                content={"detail": "runtime authentication is not configured"},
            )
        supplied = request.headers.get("X-PiPhi-Integration-Token", "")
        if expected and not hmac.compare_digest(supplied, expected):
            return JSONResponse(status_code=401, content={"detail": "invalid runtime token"})
        return await call_next(request)

    widget_dir = Path(os.getenv("PIPHI_WIDGET_DIR", Path.cwd() / "widgets"))
    if widget_dir.is_dir():
        application.mount("/widgets", StaticFiles(directory=widget_dir), name="steam-widgets")
    application.include_router(router)
    return application


app = create_app()
