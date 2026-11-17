from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from piphi_network_zigbee2mqtt.coordinator_claims import (
    CoordinatorClaimConflict,
    CoordinatorClaimStore,
    stable_coordinator_identity,
)


def test_claim_is_persistent_and_rejects_conflicting_owner(tmp_path) -> None:
    store = CoordinatorClaimStore(tmp_path / "claims")
    identity = stable_coordinator_identity("usb:sonoff:serial-123")

    store.claim(identity, "runtime-a")
    current = store.get(identity)
    assert current is not None
    CoordinatorClaimStore(tmp_path / "claims").claim(
        identity, "runtime-a", expected_generation=current.generation
    )

    with pytest.raises(CoordinatorClaimConflict, match="another runtime owner"):
        CoordinatorClaimStore(tmp_path / "claims").claim(identity, "runtime-b")

    assert (store.claim_path(identity).stat().st_mode & 0o777) == 0o600
    assert store.release(identity, "runtime-b") is False
    assert store.release(identity, "runtime-a") is True


def test_same_runtime_identity_cannot_reacquire_without_fencing_generation(tmp_path) -> None:
    store = CoordinatorClaimStore(tmp_path / "claims")
    identity = stable_coordinator_identity("usb:coordinator:restart")
    store.claim(identity, "stable-core-runtime")

    with pytest.raises(CoordinatorClaimConflict, match="generation"):
        CoordinatorClaimStore(tmp_path / "claims").claim(identity, "stable-core-runtime")


def test_claim_fails_closed_for_corrupt_state(tmp_path) -> None:
    store = CoordinatorClaimStore(tmp_path / "claims")
    path = store.claim_path("coordinator:abc")
    path.parent.mkdir()
    path.write_text("", encoding="utf-8")

    with pytest.raises(CoordinatorClaimConflict, match="invalid"):
        store.claim("coordinator:abc", "runtime-a")


def test_abrupt_crash_lease_blocks_takeover_until_authenticated_stale_repair(tmp_path) -> None:
    store = CoordinatorClaimStore(tmp_path / "claims")
    identity = stable_coordinator_identity("usb:coordinator:1")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    original = store.claim(identity, "core-runtime-a", now=now, lease_seconds=10)

    with pytest.raises(CoordinatorClaimConflict, match="another runtime owner"):
        store.claim(identity, "core-runtime-b", now=now + timedelta(seconds=11))
    with pytest.raises(CoordinatorClaimConflict, match="still live"):
        store.repair_stale(
            identity,
            requester_owner_id="core-runtime-b",
            expected_generation=original.generation,
            owner_is_live=lambda _owner: True,
            now=now + timedelta(seconds=11),
        )

    takeover = store.repair_stale(
        identity,
        requester_owner_id="core-runtime-b",
        expected_generation=original.generation,
        owner_is_live=lambda _owner: False,
        now=now + timedelta(seconds=11),
    )
    assert takeover.generation == original.generation + 1
    store.assert_fence(identity, "core-runtime-b", takeover.generation, now=now + timedelta(seconds=12))
    with pytest.raises(CoordinatorClaimConflict, match="fencing"):
        store.assert_fence(identity, "core-runtime-a", original.generation, now=now + timedelta(seconds=12))


def test_stale_repair_compare_and_swap_prevents_takeover_race(tmp_path) -> None:
    store = CoordinatorClaimStore(tmp_path / "claims")
    identity = stable_coordinator_identity("usb:coordinator:race")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    original = store.claim(identity, "core-a", now=now, lease_seconds=1)
    winner = store.repair_stale(
        identity,
        requester_owner_id="core-b",
        expected_generation=original.generation,
        owner_is_live=lambda _owner: False,
        now=now + timedelta(seconds=2),
    )
    with pytest.raises(CoordinatorClaimConflict, match="generation"):
        store.repair_stale(
            identity,
            requester_owner_id="core-c",
            expected_generation=original.generation,
            owner_is_live=lambda _owner: False,
            now=now + timedelta(seconds=2),
        )
    assert winner.owner_id == "core-b"
