from __future__ import annotations

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
    CoordinatorClaimStore(tmp_path / "claims").claim(identity, "runtime-a")

    with pytest.raises(CoordinatorClaimConflict, match="another runtime owner"):
        CoordinatorClaimStore(tmp_path / "claims").claim(identity, "runtime-b")

    assert (store.claim_path(identity).stat().st_mode & 0o777) == 0o600
    assert store.release(identity, "runtime-b") is False
    assert store.release(identity, "runtime-a") is True


def test_claim_fails_closed_for_corrupt_state(tmp_path) -> None:
    store = CoordinatorClaimStore(tmp_path / "claims")
    path = store.claim_path("coordinator:abc")
    path.parent.mkdir()
    path.write_text("", encoding="utf-8")

    with pytest.raises(CoordinatorClaimConflict, match="invalid"):
        store.claim("coordinator:abc", "runtime-a")
