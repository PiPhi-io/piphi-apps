from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from piphi_network_thinqconnect.contract.command.router import router as command_router
from piphi_network_thinqconnect.contract.config.routes import config_router
from piphi_network_thinqconnect.contract.discovery.discovery import (
    router as discovery_router,
)
from piphi_network_thinqconnect.contract.entities.router import (
    router as entities_router,
)
from piphi_network_thinqconnect.contract.events.router import router as events_router
from piphi_network_thinqconnect.contract.health.router import router as health_router
from piphi_network_thinqconnect.contract.state.router import router as state_router
from piphi_network_thinqconnect.contract.ui_schema.router import (
    router as ui_schema_router,
)
from piphi_network_thinqconnect.lib.lifespan import lifespan


def _mount_widget_assets(application: FastAPI) -> None:
    widget_dir = Path(os.getenv("PIPHI_WIDGET_DIR", Path.cwd() / "widgets"))
    if widget_dir.is_dir():
        application.mount(
            "/widgets",
            StaticFiles(directory=widget_dir),
            name="thinqconnect-overview-widgets",
        )


app = FastAPI(lifespan=lifespan)


_mount_widget_assets(app)
app.include_router(health_router)
app.include_router(command_router)
app.include_router(entities_router)
app.include_router(events_router)
app.include_router(discovery_router)
app.include_router(state_router)
app.include_router(ui_schema_router)
app.include_router(config_router)


@app.get("/contract")
async def runtime_contract() -> dict:
    manifest = json.loads((Path(__file__).parent.parent / "manifest.json").read_text())
    return {
        "integration_id": manifest["id"],
        "name": manifest["name"],
        "version": manifest["version"],
        "kind": manifest.get("kind", "integration"),
        "endpoints": {
            "health": "/health",
            "entities": "/entities",
            "events": "/events",
            "command": "/command",
            "state": "/state",
            "config": "/config",
            "config_sync": "/configs/sync",
        },
        "required": [
            "health",
            "entities",
            "events",
            "command",
            "state",
            "config",
            "config_sync",
        ],
    }


@app.get("/manifest.json")
async def display_manifest() -> dict:
    path = Path(__file__).parent.parent / "manifest.json"
    return json.loads(path.read_text())


if __name__ == "__main__":
    config = {
        "version": 1,
        "formatters": {"default": {"format": "%(asctime)s [%(levelname)s] %(message)s"}},
        "handlers": {"default": {"class": "logging.StreamHandler", "formatter": "default"}},
        "root": {"handlers": ["default"], "level": "INFO"},
    }
    multiprocessing.freeze_support()
    uvicorn.run(app, host="0.0.0.0", port=3667, log_config=config)
