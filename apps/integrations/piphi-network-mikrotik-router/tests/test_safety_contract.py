import json
from pathlib import Path

import httpx
import pytest

from piphi_network_mikrotik_router.routeros import RouterOSError, fetch_resources
from piphi_network_mikrotik_router.state import _remediation_for, _schedule_failure

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.anyio
async def test_automated_permission_denial_matrix() -> None:
    contract = json.loads((ROOT / "permission-contract.json").read_text())
    for row in contract["denial_matrix"]:
        transport = httpx.MockTransport(
            lambda _request, status=row["status"]: httpx.Response(status)
        )
        with pytest.raises(RouterOSError) as error:
            await fetch_resources(
                "router.test", "monitor", "secret", transport=transport
            )
        assert error.value.reason == row["reason"]
        assert error.value.retryable is row["retryable"]
        assert _remediation_for(error.value.reason) == row["remediation"]


def test_forbidden_permissions_and_mutations_are_not_advertised() -> None:
    contract = json.loads((ROOT / "permission-contract.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert contract["routeros_group_policies"] == ["read", "rest-api"]
    assert manifest["commands"] == {"refresh": manifest["commands"]["refresh"]}


def test_five_failures_open_a_bounded_circuit() -> None:
    entry = {"config_id": "router-test"}
    for _ in range(5):
        _schedule_failure(entry, retryable=True)
    assert entry["failure_count"] == 5
    assert entry["circuit_open_until"] > 0
    assert entry["next_poll_at"] == entry["circuit_open_until"]
