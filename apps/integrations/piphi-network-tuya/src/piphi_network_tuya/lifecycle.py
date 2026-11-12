from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .state import runtime, shutdown_runtime_resources


def _configure_logging() -> None:
    level_name = os.getenv("PIPHI_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root_logger.setLevel(level)


async def startup_sync(_runtime, _client) -> None:
    _configure_logging()
    logging.getLogger(__name__).info("PiPhi Tuya runtime startup complete")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        try:
            yield
        finally:
            await shutdown_runtime_resources()
