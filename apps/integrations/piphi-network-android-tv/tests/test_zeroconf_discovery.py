from __future__ import annotations

import asyncio

from zeroconf import ServiceStateChange

from piphi_network_android_tv.mdns_discovery import ANDROID_TV_REMOTE_V2_SERVICE
from piphi_network_android_tv.zeroconf_discovery import ZeroconfDiscoveryBackend


class FakeAsyncZeroconf:
    def __init__(self) -> None:
        self.zeroconf = object()
        self.closed = False

    async def async_close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, _zeroconf, service_type, handlers) -> None:
        self.cancelled = False
        handlers[0](
            _zeroconf,
            service_type,
            "Living Room._androidtvremote2._tcp.local.",
            ServiceStateChange.Added,
        )

    async def async_cancel(self) -> None:
        self.cancelled = True


class FakeInfo:
    def __init__(self, service_type, name) -> None:
        self.service_type = service_type
        self.name = name
        self.server = "fallback.local."
        self.port = 6466

    async def async_request(self, _zeroconf, timeout) -> bool:
        assert timeout == 100
        return True

    def parsed_scoped_addresses(self):
        return ["192.0.2.20"]


def test_backend_resolves_records_and_closes_browser() -> None:
    zeroconf = FakeAsyncZeroconf()
    browsers = []

    def browser_factory(*args, **kwargs):
        browser = FakeBrowser(*args, **kwargs)
        browsers.append(browser)
        return browser

    backend = ZeroconfDiscoveryBackend(
        browse_window_seconds=0.001,
        resolve_timeout_ms=1,
        zeroconf_factory=lambda: zeroconf,
        browser_factory=browser_factory,
        info_factory=FakeInfo,
    )

    records = asyncio.run(backend.browse(ANDROID_TV_REMOTE_V2_SERVICE))

    assert len(records) == 1
    assert records[0].host == "192.0.2.20"
    assert records[0].port == 6466
    assert browsers[0].cancelled is True
    assert zeroconf.closed is True
