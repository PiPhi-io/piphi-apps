from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .persistence import load_entries
from .state import reconcile_mqtt_subscriptions, registry, runtime, stop_mqtt_subscriptions


async def startup_sync(_runtime, _client) -> None:
    for config_id, entry in load_entries().items():
        registry.set(config_id, entry)
    reconcile_mqtt_subscriptions()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        try:
            yield
        finally:
            stop_mqtt_subscriptions()
