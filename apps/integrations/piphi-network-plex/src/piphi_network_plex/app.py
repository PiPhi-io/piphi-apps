from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

from .lifecycle import lifespan
from .routes import routers
from .settings import INTEGRATION_NAME


def create_app() -> FastAPI:
    app = FastAPI(title=INTEGRATION_NAME, lifespan=lifespan)
    for router in routers:
        app.include_router(router)
    widgets = Path(os.getenv("PIPHI_WIDGETS_PATH", str(Path(__file__).resolve().parents[2] / "widgets")))
    if widgets.is_dir():
        app.mount("/widgets", StaticFiles(directory=widgets), name="widgets")
    return app
