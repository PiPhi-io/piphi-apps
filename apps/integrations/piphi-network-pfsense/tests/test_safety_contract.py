import json
from pathlib import Path

import httpx
import pytest

from piphi_network_pfsense.pfsense_client import (
    MAX_LOG_ROWS,
    MAX_ROWS,
    PfRestV2Client,
    PfSenseError,
)
from piphi_network_pfsense.schemas import DeviceConfig

ROOT = Path(__file__).resolve().parents[1]


def test_capability_catalog_does_not_advertise_excluded_surface() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    catalog = json.loads((ROOT / "capability-catalog.json").read_text())
    implemented = {
        item
        for group in catalog["groups"]
        if group["status"] == "implemented"
        for item in group["actions"]
    }
    excluded = {
        item
        for group in catalog["groups"]
        if group["status"] == "excluded"
        for item in group["actions"]
    }
    assert implemented == set(manifest["commands"])
    assert excluded.isdisjoint(manifest["commands"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,remediation", [(401, "reauthenticate"), (403, "reconfigure_permissions")]
)
async def test_permission_denial_matrix_is_classified(
    status: int, remediation: str
) -> None:
    client = PfRestV2Client(
        DeviceConfig(id="denial", host="firewall.test", api_key="secret"),
        transport=httpx.MockTransport(lambda _request: httpx.Response(status)),
    )
    try:
        with pytest.raises(PfSenseError) as error:
            await client.read_snapshot()
        assert error.value.remediation == remediation
        assert "secret" not in str(error.value)
    finally:
        await client.close()


def test_collection_limits_are_finite() -> None:
    assert MAX_LOG_ROWS <= 200
    assert MAX_ROWS <= 1000
