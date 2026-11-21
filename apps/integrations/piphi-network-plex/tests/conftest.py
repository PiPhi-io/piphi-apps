from __future__ import annotations

import os

import pytest_asyncio

os.environ.setdefault("PIPHI_ALLOW_UNAUTHENTICATED", "true")


@pytest_asyncio.fixture(autouse=True)
async def reset_runtime_state():
    from piphi_network_plex.state import plex_service, registry, runtime

    await plex_service.close()
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime.process_state.background_tasks.clear()
    yield
    await plex_service.close()
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime.process_state.background_tasks.clear()
