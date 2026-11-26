from __future__ import annotations

import logging
import multiprocessing
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .lifespan import lifespan
from .runtime import router, runtime
from .runtime_auth import authorize_runtime_request


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [
        {
            "type": item.get("type"),
            "loc": list(item.get("loc") or []),
            "msg": item.get("msg"),
        }
        for item in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.middleware("http")
async def runtime_auth_boundary(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    allow_bootstrap = request.url.path in {
        "/config",
        "/config/sync",
        "/configs/sync",
        "/contract",
        "/discover",
        "/ui",
        "/ui-config",
    }
    try:
        authorize_runtime_request(
            request,
            runtime_context=runtime,
            allow_bootstrap=allow_bootstrap,
        )
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    return await call_next(request)


app.include_router(router)


def runtime_port_from_environment() -> int:
    raw_port = str(os.getenv("PIPHI_RUNTIME_PORT") or "3669").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("PIPHI_RUNTIME_PORT must be an integer between 1 and 65535.") from exc
    if port < 1 or port > 65535:
        raise ValueError("PIPHI_RUNTIME_PORT must be an integer between 1 and 65535.")
    return port


if __name__ == "__main__":
    import uvicorn

    config = {
        "version": 1,
        "formatters": {"default": {"format": "%(asctime)s [%(levelname)s] %(message)s"}},
        "handlers": {"default": {"class": "logging.StreamHandler", "formatter": "default"}},
        "root": {"handlers": ["default"], "level": "INFO"},
    }
    multiprocessing.freeze_support()
    uvicorn.run(app, host="0.0.0.0", port=runtime_port_from_environment(), log_config=config)
