from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME
from .tuya import TuyaClientError


def _tuya_error_status_code(message: str) -> int:
    lowered = message.strip().lower()
    if "already configured" in lowered:
        return 409
    if "timed out" in lowered:
        return 504
    if any(
        token in lowered for token in {"requires", "missing", "unsupported command"}
    ):
        return 422
    if "not installed" in lowered or "unavailable" in lowered:
        return 503
    return 502


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)

    @app.exception_handler(TuyaClientError)
    async def handle_tuya_client_error(_request: Request, exc: TuyaClientError):
        message = str(exc)
        return JSONResponse(
            status_code=_tuya_error_status_code(message),
            content={
                "ok": False,
                "error": {
                    "type": "tuya_client_error",
                    "message": message,
                },
            },
        )

    for router in routers:
        app.include_router(router)
    return app
