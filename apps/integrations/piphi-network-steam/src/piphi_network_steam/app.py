from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .lifespan import lifespan
from .runtime import router


def create_app() -> FastAPI:
    application = FastAPI(title="PiPhi Network Steam", lifespan=lifespan)
    widget_dir = Path(os.getenv("PIPHI_WIDGET_DIR", Path.cwd() / "widgets"))
    if widget_dir.is_dir():
        application.mount("/widgets", StaticFiles(directory=widget_dir), name="steam-widgets")
    application.include_router(router)
    return application


app = create_app()
