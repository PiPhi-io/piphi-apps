from __future__ import annotations

import json

import httpx
import pytest

from piphi_network_pfsense.pfsense_client import PfRestV2Client, PfSenseError
from piphi_network_pfsense.schemas import DeviceConfig


def config(**changes) -> DeviceConfig:
    values = {
        "id": "firewall-1",
        "host": "pfsense.test",
        "api_key": "secret-key",
        "scheme": "https",
    }
    values.update(changes)
    return DeviceConfig(**values)


@pytest.mark.anyio
async def test_reads_and_unwraps_pfrest_v2_snapshot() -> None:
    responses = {
        "/api/v2/status/system": {"data": {"platform": "pfSense", "cpu_usage": 17}},
        "/api/v2/system/version": {"data": {"version": "2.8.1-RELEASE"}},
        "/api/v2/system/restapi/version": {"data": {"current_version": "2.9.0"}},
        "/api/v2/status/interfaces": {"data": [{"name": "wan", "status": "up"}]},
        "/api/v2/status/gateways": {"data": [{"name": "WAN_DHCP", "status": "online"}]},
        "/api/v2/status/services": {"data": [{"name": "unbound", "status": True}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "secret-key"
        return httpx.Response(200, json=responses[request.url.path])

    client = PfRestV2Client(config(), transport=httpx.MockTransport(handler))
    try:
        snapshot = await client.read_snapshot()
    finally:
        await client.close()

    assert snapshot.system["cpu_usage"] == 17
    assert snapshot.version["version"] == "2.8.1-RELEASE"
    assert snapshot.interfaces[0]["name"] == "wan"
    assert snapshot.gateways[0]["status"] == "online"
    assert snapshot.endpoint_errors == {}


@pytest.mark.anyio
async def test_optional_endpoint_failure_does_not_drop_system_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/status/system":
            return httpx.Response(200, json={"data": {"platform": "pfSense"}})
        if request.url.path == "/api/v2/status/gateways":
            return httpx.Response(403, json={"message": "forbidden"})
        return httpx.Response(200, json={"data": []})

    client = PfRestV2Client(config(), transport=httpx.MockTransport(handler))
    try:
        snapshot = await client.read_snapshot()
    finally:
        await client.close()

    assert snapshot.system["platform"] == "pfSense"
    assert "HTTP 403" in snapshot.endpoint_errors["gateways"]


@pytest.mark.anyio
async def test_optional_inventory_certificates_ha_and_logs_are_collected_safely() -> (
    None
):
    responses = {
        "/api/v2/status/system": {"data": {"platform": "pfSense"}},
        "/api/v2/status/dhcp_server/leases": {"data": [{"ip": "192.0.2.10"}]},
        "/api/v2/diagnostics/arp_table": {"data": [{"ip_address": "192.0.2.10"}]},
        "/api/v2/system/certificates": {
            "data": [
                {
                    "id": 1,
                    "refid": "cert-1",
                    "descr": "Web UI",
                    "valid_days_left": 20,
                    "crt": "certificate-data",
                    "prv": "private-key-data",
                }
            ]
        },
        "/api/v2/status/carp": {"data": {"enable": True}},
        "/api/v2/firewall/virtual_ips": {"data": [{"mode": "carp"}]},
        "/api/v2/system/hasync": {
            "data": {"pfsyncenabled": True, "password": "secret"}
        },
        "/api/v2/status/logs/firewall": {"data": [{"text": "blocked packet"}]},
        "/api/v2/status/logs/auth": {"data": []},
        "/api/v2/status/logs/dhcp": {"data": []},
        "/api/v2/status/logs/system": {"data": []},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.get(request.url.path, {"data": []}))

    client = PfRestV2Client(
        config(
            collect_client_inventory=True,
            collect_certificates=True,
            collect_ha_status=True,
            collect_security_logs=True,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        snapshot = await client.read_snapshot()
    finally:
        await client.close()

    assert snapshot.arp_entries[0]["ip_address"] == "192.0.2.10"
    assert snapshot.certificates[0]["valid_days_left"] == 20
    assert "crt" not in snapshot.certificates[0]
    assert "prv" not in snapshot.certificates[0]
    assert "password" not in snapshot.ha_sync
    assert snapshot.logs["firewall"][0]["text"] == "blocked packet"


@pytest.mark.anyio
async def test_required_auth_failure_is_safe_and_actionable() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(401, json={"message": "bad key"})
    )
    client = PfRestV2Client(config(), transport=transport)
    try:
        with pytest.raises(PfSenseError) as exc_info:
            await client.read_snapshot()
    finally:
        await client.close()

    assert "check API-key privileges" in str(exc_info.value)
    assert "secret-key" not in str(exc_info.value)


@pytest.mark.anyio
async def test_operational_actions_use_typed_write_endpoints() -> None:
    requests: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/api/v2/status/services" and request.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"id": 7, "name": "unbound", "status": True}]},
            )
        if request.url.path == "/api/v2/diagnostics/ping":
            return httpx.Response(
                200,
                json={"data": {"output": "3 packets received", "result_code": 0}},
            )
        if request.url.path == "/api/v2/status/service":
            return httpx.Response(
                200,
                json={"data": {"id": 7, "name": "unbound", "status": True}},
            )
        if request.url.path == "/api/v2/services/wake_on_lan/send":
            return httpx.Response(200, json={"data": body})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = PfRestV2Client(config(), transport=httpx.MockTransport(handler))
    try:
        ping = await client.diagnostic_ping("1.1.1.1", count=3)
        restarted = await client.restart_service("UNBOUND")
        started = await client.start_service("unbound")
        woken = await client.wake_on_lan(interface="lan", mac_addr="aa:bb:cc:dd:ee:ff")
    finally:
        await client.close()

    assert ping["result_code"] == 0
    assert restarted["status"] is True
    assert started["status"] is True
    assert woken["interface"] == "lan"
    assert (
        "POST",
        "/api/v2/diagnostics/ping",
        {"host": "1.1.1.1", "count": 3},
    ) in requests
    assert (
        "POST",
        "/api/v2/status/service",
        {"id": 7, "action": "start"},
    ) in requests
    assert (
        "POST",
        "/api/v2/services/wake_on_lan/send",
        {"interface": "lan", "mac_addr": "aa:bb:cc:dd:ee:ff"},
    ) in requests
    assert (
        "POST",
        "/api/v2/status/service",
        {"id": 7, "action": "restart"},
    ) in requests
