from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .go2rtc import go2rtc_process
from .media_sessions import media_session_broker


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await go2rtc_process.start()
    try:
        yield
    finally:
        await media_session_broker.close_all()
        await go2rtc_process.stop()
