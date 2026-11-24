import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from com_piphi_await_element.contract.command.router import router as command_router
from com_piphi_await_element.contract.config.routes import config_router
from com_piphi_await_element.contract.discovery.discovery import discovery_router
from com_piphi_await_element.contract.entities.router import router as entities_router
from com_piphi_await_element.contract.events.router import router as events_router
from com_piphi_await_element.contract.health.router import router as health_router
from com_piphi_await_element.contract.state.router import router as state_router
from com_piphi_await_element.contract.ui_schema.router import router as ui_schema
from com_piphi_await_element.lib.lifespan import lifespan
from com_piphi_await_element.lib.logging import configure_logging
from com_piphi_await_element.lib.manifest import load_manifest

configure_logging()

app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def require_runtime_auth(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path.rstrip("/") == "/health":
        return await call_next(request)
    expected = os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
    allow_unauthenticated = os.getenv("PIPHI_ALLOW_UNAUTHENTICATED", "").lower() == "true"
    if not expected and not allow_unauthenticated:
        return JSONResponse(
            status_code=503,
            content={"detail": "runtime authentication is not configured"},
        )
    supplied = request.headers.get("X-PiPhi-Integration-Token", "")
    if expected and not hmac.compare_digest(supplied, expected):
        return JSONResponse(status_code=401, content={"detail": "invalid runtime token"})
    return await call_next(request)

app.include_router(health_router)
app.include_router(command_router)
app.include_router(entities_router)
app.include_router(events_router)
app.include_router(discovery_router)
app.include_router(state_router)

app.include_router(router=ui_schema)

app.include_router(router=config_router)

@app.get("/manifest.json")
async def display_manifest():
    return load_manifest()
