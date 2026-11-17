import json
from pathlib import Path

import httpx
import pytest

from piphi_network_pfsense.pfsense_client import (
    MAX_LOG_ROWS,
    MAX_ROWS,
    PfRestV2Client,
    PfSenseError,
    _structured_log_record,
)
from piphi_network_pfsense.schemas import DeviceConfig, classify_service_control

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


@pytest.mark.parametrize(
    "service",
    [
        "unbound",
        "dhcpd",
        "openvpn-client-1",
        "wireguard",
        "carp",
        "routing",
        "webConfigurator",
        "api-service",
        "radius-auth",
        "unknown-package",
    ],
)
def test_critical_and_unclassified_service_controls_fail_closed(service: str) -> None:
    assert classify_service_control(service).endswith("denied")
    with pytest.raises(ValueError, match="critical or unclassified"):
        DeviceConfig(
            id="unsafe-service",
            host="firewall.test",
            api_key="secret",
            enable_service_restart=True,
            allowed_services=[service],
        )


def test_log_fingerprint_is_derived_only_after_sensitive_redaction() -> None:
    first = _structured_log_record(
        {
            "text": "login user=alice from 8.8.8.8 at edge.example.com https://edge.example.com/path?token=one",
            "interface": "wan-secret-vlan",
        }
    )
    second = _structured_log_record(
        {
            "text": "login user=bob from 1.1.1.1 at other.example.net https://other.example.net/path?token=two",
            "interface": "private-interface",
        }
    )
    serialized = json.dumps([first, second])
    for raw in (
        "alice",
        "bob",
        "8.8.8.8",
        "1.1.1.1",
        "edge.example.com",
        "other.example.net",
        "token=one",
        "token=two",
        "wan-secret-vlan",
        "private-interface",
    ):
        assert raw not in serialized
    assert first["event_id"] == second["event_id"]


@pytest.mark.anyio
async def test_content_length_is_rejected_before_body_buffering() -> None:
    client = PfRestV2Client(
        DeviceConfig(id="large", host="firewall.test", api_key="secret"),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-length": "2000000"},
                content=b'{"data": {}}',
            )
        ),
    )
    try:
        with pytest.raises(PfSenseError, match="response_size_limit_exceeded"):
            await client.read_snapshot()
    finally:
        await client.close()
