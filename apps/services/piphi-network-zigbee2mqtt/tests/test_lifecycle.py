from __future__ import annotations

from types import SimpleNamespace

import pytest

from piphi_network_zigbee2mqtt import lifecycle


@pytest.mark.anyio
async def test_claim_heartbeat_renews_active_fencing_lease(monkeypatch) -> None:
    calls: list[tuple[str, str, int]] = []
    sleeps = 0

    async def fake_sleep(_seconds: int) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise RuntimeError("heartbeat_complete")

    monkeypatch.setattr(lifecycle.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        lifecycle.claim_store,
        "renew",
        lambda identity, owner_id, generation: (
            calls.append((identity, owner_id, generation))
            or SimpleNamespace(generation=generation)
        ),
    )
    monkeypatch.setattr(lifecycle.sidecar_store, "coordinator_identity", "coordinator:test")
    monkeypatch.setattr(lifecycle.sidecar_store, "coordinator_owner_id", "core-runtime:test")
    monkeypatch.setattr(lifecycle.sidecar_store, "coordinator_claim_generation", 4)

    with pytest.raises(RuntimeError, match="heartbeat_complete"):
        await lifecycle._renew_coordinator_claim()

    assert calls == [("coordinator:test", "core-runtime:test", 4)]
