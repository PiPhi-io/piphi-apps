from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)
    for router in routers:
        app.include_router(router)
    widget_dir = Path(os.getenv("PIPHI_WIDGET_DIR", Path(__file__).resolve().parents[2] / "widgets"))
    if widget_dir.is_dir():
        app.mount("/widgets", StaticFiles(directory=widget_dir), name="sense-widgets")
    return app
