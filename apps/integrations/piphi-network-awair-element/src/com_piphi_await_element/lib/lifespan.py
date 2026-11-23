import asyncio
import contextlib
from typing import Any

from fastapi import FastAPI
from piphi_runtime_kit_python import (
    rehydrate_runtime_configs,
    resolve_core_base_url,
    runtime_lifespan,
)
from zeroconf import ServiceListener, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from com_piphi_await_element.contract.config.routes import restore_runtime_config_snapshot
from com_piphi_await_element.lib.logging import log_event
from com_piphi_await_element.lib.schemas import AwairElement, RuntimeConfigSnapshot
from com_piphi_await_element.lib.store import get_runtime_context

DISCOVERY_SERVICE_TYPES = ["_http._tcp.local.", "_awair._tcp.local.", "_hap._tcp.local."]
CORE_BASE_URL = resolve_core_base_url("http://127.0.0.1:31419")
CORE_REQUEST_TIMEOUT_SECONDS = 10.0

config: dict[str, dict[str, Any]] = {}
runtime_context = get_runtime_context()


class ZeroConfGlobalListener(ServiceListener):
    def __init__(self, aiozc: AsyncZeroconf):
        self.aiozc = aiozc

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        log_event("service_updated", type=type_)
        asyncio.create_task(self._handle_service(type_, name))

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        log_event("service_removed", type=type_)
        config.pop(name, None)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        log_event("service_discovered", type=type_)
        asyncio.create_task(self._handle_service(type_, name))

    async def _handle_service(self, type_: str, name: str) -> None:
        info = AsyncServiceInfo(type_, name)
        await info.async_request(self.aiozc.zeroconf, 3000)

        if info and info.addresses:
            addresses = list(info.parsed_addresses())
            config[name] = {
                "name": name,
                "type": type_,
                "addresses": addresses,
                "port": info.port,
                "meta": {
                    key.decode("utf-8", errors="ignore"): value.decode("utf-8", errors="ignore")
                    for key, value in info.properties.items() if value is not None
                },
            }
            if "awair" in name.lower():
                log_event("awair_discovered", type=type_)


async def query_specific_awair(
    service_name: str,
    service_type: str = "_http._tcp.local.",
) -> dict[str, Any] | None:
    """Query for one specific Awair service name."""
    aiozc = AsyncZeroconf()

    full_name = (
        f"{service_name}.{service_type}"
        if not service_name.endswith(service_type)
        else service_name
    )

    info = AsyncServiceInfo(service_type, full_name)
    log_event("query_specific_device", type=service_type)
    success = await info.async_request(aiozc.zeroconf, 3000)

    result: dict[str, Any] | None = None
    if success and info.addresses:
        addresses = list(info.parsed_addresses())
        result = {
            "name": full_name,
            "type": service_type,
            "addresses": addresses,
            "port": info.port,
            "meta": {
                key.decode("utf-8", errors="ignore"): value.decode("utf-8", errors="ignore")
                for key, value in info.properties.items() if value is not None
            },
        }
        log_event("query_specific_device_found", type=service_type)
    else:
        log_event("query_specific_device_not_found", level="warning", type=service_type)

    await aiozc.async_close()
    return result


async def discover_awair_actively(timeout: int = 10) -> dict[str, dict[str, Any]]:
    """Active discovery of Awair devices via PTR queries."""
    aiozc = AsyncZeroconf()
    listener = ZeroConfGlobalListener(aiozc)

    browsers = [
        AsyncServiceBrowser(aiozc.zeroconf, service_type, listener)
        for service_type in DISCOVERY_SERVICE_TYPES
    ]

    log_event("awair_discovery_start")
    await asyncio.sleep(timeout)

    awair_devices = {
        name: info for name, info in config.items() if "awair" in name.lower()
    }
    for _name in awair_devices:
        log_event("awair_discovery_result")

    for browser in browsers:
        await browser.async_cancel()
    await aiozc.async_close()

    log_event("awair_discovery_complete", count=len(awair_devices))
    return awair_devices


async def find_awair_with_retry(
    max_attempts: int = 3,
    timeout: int = 8,
) -> dict[str, dict[str, Any]]:
    for attempt in range(1, max_attempts + 1):
        log_event("awair_discovery_attempt", current=attempt, total=max_attempts)

        config.clear()
        discovered = await discover_awair_actively(timeout)

        if discovered:
            return discovered

        if attempt < max_attempts:
            await asyncio.sleep(2)

    return {}


async def startup_sync(runtime, client) -> None:
    result = await rehydrate_runtime_configs(
        runtime_context=runtime,
        client=client,
        apply_snapshot=restore_runtime_config_snapshot,
        config_model=AwairElement,
        snapshot_model=RuntimeConfigSnapshot,
        core_base_url=CORE_BASE_URL,
        timeout_seconds=CORE_REQUEST_TIMEOUT_SECONDS,
    )

    if result.snapshot_applied:
        log_event(
            "awair_startup_rehydrate_complete",
            loaded=result.snapshot_config_count,
            generation=result.snapshot_generation,
            source="snapshot",
        )
    else:
        log_event("awair_startup_snapshot_rehydrate_skipped", reason="missing_snapshot")

    if result.core_applied:
        log_event(
            "awair_startup_rehydrate_complete",
            loaded=result.core_config_count,
            generation=result.core_generation,
            source="core",
        )
        return

    if result.core_error:
        log_event(
            "awair_startup_core_rehydrate_failed",
            level="warning",
            error=result.core_error,
        )
    elif result.missing_runtime_auth:
        log_event("awair_startup_rehydrate_skipped", reason="missing_runtime_auth")
    elif result.core_attempted:
        log_event("awair_startup_rehydrate_no_configs", source="core")

    if result.snapshot_applied:
        log_event("awair_startup_rehydrate_using_snapshot", reason="core_unavailable")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    aiozc = AsyncZeroconf()
    listener = ZeroConfGlobalListener(aiozc)

    browsers = [
        AsyncServiceBrowser(aiozc.zeroconf, service_type, listener)
        for service_type in DISCOVERY_SERVICE_TYPES
    ]

    log_event("awair_lifespan_start")

    async with runtime_lifespan(
        runtime_context,
        on_startup=startup_sync,
        core_client_timeout_seconds=CORE_REQUEST_TIMEOUT_SECONDS,
    ):
        try:
            yield
        finally:
            for browser in browsers:
                await browser.async_cancel()
            await aiozc.async_close()
            log_event("awair_lifespan_shutdown")
