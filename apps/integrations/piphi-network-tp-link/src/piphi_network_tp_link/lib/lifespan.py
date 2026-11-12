import contextlib

from fastapi import FastAPI
from httpx import AsyncClient
from piphi_runtime_kit_python import (
    rehydrate_runtime_configs,
    resolve_core_base_url,
    runtime_lifespan,
)

from piphi_network_tp_link.contract.config.routes import (
    apply_runtime_config_snapshot,
)
from piphi_network_tp_link.lib.logging import logger
from piphi_network_tp_link.lib.schemas import RuntimeConfigSnapshot, TPLinkDeviceConfig
from piphi_network_tp_link.lib.store import get_runtime_context

CORE_BASE_URL = resolve_core_base_url("http://127.0.0.1:31419")
CORE_REQUEST_TIMEOUT_SECONDS = 10.0
runtime_context = get_runtime_context()


async def startup_sync(runtime, core_http_client: AsyncClient) -> None:
    result = await rehydrate_runtime_configs(
        runtime_context=runtime,
        client=core_http_client,
        apply_snapshot=apply_runtime_config_snapshot,
        config_model=TPLinkDeviceConfig,
        snapshot_model=RuntimeConfigSnapshot,
        core_base_url=CORE_BASE_URL,
        timeout_seconds=CORE_REQUEST_TIMEOUT_SECONDS,
    )

    if result.snapshot_applied:
        logger.info(
            "kasa_startup_rehydrate_complete loaded=%s generation=%s source=snapshot",
            result.snapshot_config_count,
            result.snapshot_generation,
        )

    if result.core_applied:
        logger.info(
            "kasa_startup_rehydrate_complete loaded=%s generation=%s source=core",
            result.core_config_count,
            result.core_generation,
        )
        return

    if result.core_error:
        logger.warning("kasa_startup_core_rehydrate_failed error=%s", result.core_error)
    elif result.missing_runtime_auth:
        logger.warning(
            "kasa_startup_missing_runtime_credentials "
            "standalone_mode=true"
        )
    elif result.core_attempted:
        logger.info("kasa_startup_rehydrate_no_configs")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("kasa_lifespan_start")
    async with runtime_lifespan(
        runtime_context,
        on_startup=startup_sync,
        core_client_timeout_seconds=CORE_REQUEST_TIMEOUT_SECONDS,
    ):
        try:
            yield
        finally:
            logger.info("kasa_lifespan_shutdown")
