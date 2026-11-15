from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from piphi_network_android_tv.mdns_discovery import (
    ANDROID_TV_REMOTE_V2_SERVICE,
    MAX_DISCOVERY_TIMEOUT_SECONDS,
    MdnsService,
    RemoteV2MdnsDiscovery,
)


class FakeBackend:
    def __init__(self, records: Iterable[MdnsService | Mapping[str, Any]]) -> None:
        self.records = records
        self.requests: list[str] = []

    async def browse(
        self, service_type: str
    ) -> Iterable[MdnsService | Mapping[str, Any]]:
        self.requests.append(service_type)
        return self.records


def test_discovers_only_remote_v2_and_marks_candidates_unverified() -> None:
    backend = FakeBackend(
        [
            MdnsService(
                "_ANDROIDTVREMOTE2._TCP.LOCAL",
                "  Living   Room._androidtvremote2._tcp.local. ",
                "TV-ONE.Local.",
                "6466",
            ),
            MdnsService(
                "_googlecast._tcp.local.", "Not Remote v2", "cast.local.", 8009
            ),
        ]
    )

    candidates = asyncio.run(RemoteV2MdnsDiscovery(backend).discover())

    assert backend.requests == [ANDROID_TV_REMOTE_V2_SERVICE]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.name == "Living Room"
    assert candidate.host == "tv-one.local"
    assert candidate.port == 6466
    assert candidate.service_type == ANDROID_TV_REMOTE_V2_SERVICE
    assert candidate.verification_status == "unverified"
    assert candidate.stable_device_id is None
    assert not hasattr(candidate, "device_id")


def test_normalizes_and_deduplicates_announcements_deterministically() -> None:
    backend = FakeBackend(
        [
            MdnsService(
                ANDROID_TV_REMOTE_V2_SERVICE, "Kitchen", "TV.Local.", 6466
            ),
            MdnsService(
                ANDROID_TV_REMOTE_V2_SERVICE,
                "bedroom",
                "[2001:0DB8::1]",
                6466,
            ),
            MdnsService(
                ANDROID_TV_REMOTE_V2_SERVICE, "Kitchen", "tv.local", "6466"
            ),
            MdnsService(
                ANDROID_TV_REMOTE_V2_SERVICE,
                "BEDROOM",
                "2001:db8:0:0::1",
                6466,
            ),
        ]
    )

    candidates = asyncio.run(RemoteV2MdnsDiscovery(backend).discover())

    assert [(item.name, item.host, item.port) for item in candidates] == [
        ("BEDROOM", "2001:db8::1", 6466),
        ("Kitchen", "tv.local", 6466),
    ]


def test_malformed_records_are_ignored_without_fabricating_candidates() -> None:
    backend = FakeBackend(
        [
            {},
            {
                "service_type": ANDROID_TV_REMOTE_V2_SERVICE,
                "name": "",
                "host": "tv.local",
                "port": 6466,
            },
            {
                "service_type": ANDROID_TV_REMOTE_V2_SERVICE,
                "name": "TV",
                "host": "https://tv.local",
                "port": 6466,
            },
            {
                "service_type": ANDROID_TV_REMOTE_V2_SERVICE,
                "name": "TV",
                "host": "tv.local",
                "port": 0,
            },
            {
                "service_type": ANDROID_TV_REMOTE_V2_SERVICE,
                "name": "TV",
                "host": "tv.local",
                "port": True,
            },
            {
                "service_type": None,
                "name": "TV",
                "host": "tv.local",
                "port": 6466,
            },
        ]
    )

    assert asyncio.run(RemoteV2MdnsDiscovery(backend).discover()) == ()


def test_discovery_timeout_is_bounded_and_cancels_backend() -> None:
    class BlockingBackend:
        def __init__(self) -> None:
            self.cancelled = asyncio.Event()

        async def browse(self, service_type: str) -> Iterable[MdnsService]:
            assert service_type == ANDROID_TV_REMOTE_V2_SERVICE
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
            return ()

    async def scenario() -> None:
        backend = BlockingBackend()
        discovery = RemoteV2MdnsDiscovery(backend, timeout_seconds=0.01)
        assert await discovery.discover() == ()
        assert backend.cancelled.is_set()

    asyncio.run(scenario())


def test_timeout_configuration_is_validated_and_capped() -> None:
    backend = FakeBackend([])
    for value in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            RemoteV2MdnsDiscovery(backend, timeout_seconds=value)
    with pytest.raises(TypeError):
        RemoteV2MdnsDiscovery(backend, timeout_seconds=True)

    discovery = RemoteV2MdnsDiscovery(
        backend, timeout_seconds=MAX_DISCOVERY_TIMEOUT_SECONDS * 100
    )
    assert discovery.timeout_seconds == MAX_DISCOVERY_TIMEOUT_SECONDS
