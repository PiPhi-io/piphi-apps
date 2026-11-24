import json
import hmac
import os
import multiprocessing
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiofiles
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from piphi_network_tp_link.contract.command.router import router as command_router
from piphi_network_tp_link.contract.config.routes import config_router
from piphi_network_tp_link.contract.discovery.discovery import router as discovery_router
from piphi_network_tp_link.contract.entities.router import router as entities_router
from piphi_network_tp_link.contract.events.router import router as events_router
from piphi_network_tp_link.contract.health.router import router as health_router
from piphi_network_tp_link.contract.state.router import router as state_router
from piphi_network_tp_link.contract.ui_schema.router import router as ui_schema_router
from piphi_network_tp_link.lib.lifespan import lifespan

app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def require_runtime_auth(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path.rstrip("/") == "/health":
        return await call_next(request)
    expected = os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
    if not expected:
        return JSONResponse(
            status_code=503,
            content={"detail": "runtime authentication is not configured"},
        )
    supplied = request.headers.get("X-PiPhi-Integration-Token", "")
    if not hmac.compare_digest(supplied, expected):
        return JSONResponse(status_code=401, content={"detail": "invalid runtime token"})
    return await call_next(request)

app.include_router(health_router)
app.include_router(command_router)
app.include_router(entities_router)
app.include_router(events_router)
app.include_router(discovery_router)
app.include_router(state_router)
app.include_router(ui_schema_router)
app.include_router(config_router)


@app.get("/manifest.json")
async def display_manifest() -> dict:
    path = Path(__file__).parent.parent / "manifest.json"
    async with aiofiles.open(path) as f:
        return json.loads(await f.read())


if __name__ == "__main__":
    config = {
        "version": 1,
        "formatters": {"default": {"format": "%(asctime)s [%(levelname)s] %(message)s"}},
        "handlers": {"default": {"class": "logging.StreamHandler", "formatter": "default"}},
        "root": {"handlers": ["default"], "level": "INFO"},
    }
    multiprocessing.freeze_support()
    uvicorn.run(app, host="0.0.0.0", port=4185, log_config=config)
