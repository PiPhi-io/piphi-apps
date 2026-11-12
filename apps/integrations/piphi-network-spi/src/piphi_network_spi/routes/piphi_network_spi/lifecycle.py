from __future__ import annotations

from contextlib import asynccontextmanager

from piphi_runtime_kit_python import runtime_lifespan

from .state import runtime


@asynccontextmanager
async def lifespan(_app):
    async with runtime_lifespan(runtime):
        yield
