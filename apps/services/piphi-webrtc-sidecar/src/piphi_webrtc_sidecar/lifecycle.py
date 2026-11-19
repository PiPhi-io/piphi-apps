from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .analysis_media import analysis_media_broker
from .go2rtc import go2rtc_process
from .media_sessions import media_session_broker


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await go2rtc_process.start()
    try:
        yield
    finally:
        try:
            await analysis_media_broker.close_all()
        finally:
            try:
                await media_session_broker.close_all()
            finally:
                await go2rtc_process.stop()
