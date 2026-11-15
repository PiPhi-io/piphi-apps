from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from .mdns_discovery import MdnsService


class ZeroconfDiscoveryBackend:
    """Short-lived mDNS browser for Android TV Remote v2 service records."""

    def __init__(
        self,
        *,
        browse_window_seconds: float = 2.0,
        resolve_timeout_ms: float = 1_000,
        zeroconf_factory: Callable[[], Any] = AsyncZeroconf,
        browser_factory: Callable[..., Any] = AsyncServiceBrowser,
        info_factory: Callable[..., Any] = AsyncServiceInfo,
    ) -> None:
        self._browse_window_seconds = max(0.05, min(float(browse_window_seconds), 5.0))
        self._resolve_timeout_ms = max(100.0, min(float(resolve_timeout_ms), 3_000.0))
        self._zeroconf_factory = zeroconf_factory
        self._browser_factory = browser_factory
        self._info_factory = info_factory

    async def browse(self, service_type: str) -> tuple[MdnsService, ...]:
        async_zeroconf = self._zeroconf_factory()
        tasks: list[asyncio.Task[MdnsService | None]] = []

        async def resolve(name: str) -> MdnsService | None:
            info = self._info_factory(service_type, name)
            if not await info.async_request(
                async_zeroconf.zeroconf,
                timeout=self._resolve_timeout_ms,
            ):
                return None
            addresses = info.parsed_scoped_addresses()
            host = addresses[0] if addresses else info.server
            if not host:
                return None
            return MdnsService(
                service_type=service_type,
                name=name,
                host=host,
                port=info.port,
            )

        def on_service_state_change(
            _zeroconf: Any,
            _service_type: str,
            name: str,
            state_change: ServiceStateChange,
        ) -> None:
            if state_change not in {ServiceStateChange.Added, ServiceStateChange.Updated}:
                return
            task = asyncio.create_task(resolve(name))
            tasks.append(task)

        browser = self._browser_factory(
            async_zeroconf.zeroconf,
            service_type,
            handlers=[on_service_state_change],
        )
        results: list[MdnsService] = []
        try:
            await asyncio.sleep(self._browse_window_seconds)
            if tasks:
                resolved = await asyncio.gather(*tuple(tasks), return_exceptions=True)
                results.extend(item for item in resolved if isinstance(item, MdnsService))
        finally:
            await browser.async_cancel()
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tuple(tasks), return_exceptions=True)
            await async_zeroconf.async_close()
        return tuple(results)
