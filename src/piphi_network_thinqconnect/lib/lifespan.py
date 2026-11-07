from __future__ import annotations

import contextlib

from fastapi import FastAPI
from httpx import AsyncClient
from piphi_runtime_kit_python import runtime_lifespan

from piphi_network_thinqconnect.contract.config.routes import (
    apply_runtime_config_snapshot,
    shutdown_background_tasks,
)
from piphi_network_thinqconnect.lib.logging import logger
from piphi_network_thinqconnect.lib.schemas import (
    RuntimeConfigSnapshot,
    ThinQDeviceConfig,
)
from piphi_network_thinqconnect.lib.store import runtime_context, starter

CORE_REQUEST_TIMEOUT_SECONDS = 10.0


async def startup_sync(_runtime, core_http_client: AsyncClient) -> None:
    result = await starter.rehydrate_configs(
        client=core_http_client,
        apply_snapshot=apply_runtime_config_snapshot,
        config_model=ThinQDeviceConfig,
        snapshot_model=RuntimeConfigSnapshot,
        timeout_seconds=CORE_REQUEST_TIMEOUT_SECONDS,
    )

    if result.snapshot_applied:
        logger.info(
            "thinq_startup_rehydrate_complete loaded=%s generation=%s source=snapshot",
            result.snapshot_config_count,
            result.snapshot_generation,
        )

    if result.core_applied:
        logger.info(
            "thinq_startup_rehydrate_complete loaded=%s generation=%s source=core",
            result.core_config_count,
            result.core_generation,
        )
        return

    if result.core_error:
        logger.warning("thinq_startup_core_rehydrate_failed error=%s", result.core_error)
    elif result.missing_runtime_auth:
        logger.warning("thinq_startup_missing_runtime_credentials standalone_mode=true")
    elif result.core_attempted:
        logger.info("thinq_startup_rehydrate_no_configs")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("thinq_lifespan_start")
    async with runtime_lifespan(
        runtime_context,
        on_startup=startup_sync,
        core_client_timeout_seconds=CORE_REQUEST_TIMEOUT_SECONDS,
    ):
        try:
            yield
        finally:
            await shutdown_background_tasks()
            logger.info("thinq_lifespan_shutdown")
