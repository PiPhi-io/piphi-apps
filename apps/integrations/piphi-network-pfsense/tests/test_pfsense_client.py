from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from piphi_network_pfsense import pfsense_client
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
async def test_baseline_permission_failure_fails_the_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/status/system":
            return httpx.Response(200, json={"data": {"platform": "pfSense"}})
        if request.url.path == "/api/v2/status/gateways":
            return httpx.Response(403, json={"message": "forbidden"})
        return httpx.Response(200, json={"data": []})

    client = PfRestV2Client(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(PfSenseError, match="baseline profile.*gateways"):
            await client.read_snapshot()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_optional_inventory_certificates_ha_and_logs_are_collected_safely() -> (
    None
):
    responses = {
        "/api/v2/status/system": {"data": {"platform": "pfSense"}},
        "/api/v2/system/version": {"data": {"version": "2.8.1"}},
        "/api/v2/system/restapi/version": {"data": {"current_version": "2.9.0"}},
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
    assert "text" not in snapshot.logs["firewall"][0]
    assert snapshot.logs["firewall"][0]["event_id"]


@pytest.mark.anyio
async def test_optional_endpoint_failure_survives_as_scoped_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/status/logs/auth":
            return httpx.Response(403)
        if request.url.path == "/api/v2/status/system":
            return httpx.Response(200, json={"data": {"serial": "TEST"}})
        if request.url.path == "/api/v2/system/restapi/version":
            return httpx.Response(200, json={"data": {"current_version": "2.9.0"}})
        if request.url.path == "/api/v2/system/version":
            return httpx.Response(200, json={"data": {"version": "fixture"}})
        return httpx.Response(200, json={"data": []})

    client = PfRestV2Client(
        config(collect_security_logs=True), transport=httpx.MockTransport(handler)
    )
    try:
        snapshot = await client.read_snapshot()
    finally:
        await client.close()
    assert snapshot.system["serial"] == "TEST"
    assert snapshot.endpoint_errors == {"log_auth": "permission_denied"}


@pytest.mark.anyio
async def test_process_global_concurrency_is_bounded_across_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum = 0
    monkeypatch.setattr(
        pfsense_client, "_GLOBAL_ENDPOINT_SLOTS", asyncio.Semaphore(2)
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={"data": {}})

    clients = [
        PfRestV2Client(
            config(id=f"firewall-{index}", host=f"firewall-{index}.test"),
            transport=httpx.MockTransport(handler),
        )
        for index in range(6)
    ]
    try:
        await asyncio.gather(
            *(client._get("/api/v2/status/system") for client in clients)
        )
    finally:
        await asyncio.gather(*(client.close() for client in clients))
    assert maximum == 2


@pytest.mark.anyio
async def test_per_appliance_concurrency_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum = 0
    monkeypatch.setattr(
        pfsense_client, "_GLOBAL_ENDPOINT_SLOTS", asyncio.Semaphore(20)
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={"data": {}})

    client = PfRestV2Client(config(), transport=httpx.MockTransport(handler))
    try:
        await asyncio.gather(
            *(client._get(f"/api/v2/test/{index}") for index in range(12))
        )
    finally:
        await client.close()
    assert maximum == pfsense_client.MAX_ENDPOINT_CONCURRENCY


@pytest.mark.anyio
async def test_rate_limit_retry_after_is_parsed_and_bounded() -> None:
    client = PfRestV2Client(
        config(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, headers={"Retry-After": "1200"})
        ),
    )
    try:
        with pytest.raises(PfSenseError) as exc_info:
            await client._get("/api/v2/status/system")
    finally:
        await client.close()
    assert exc_info.value.reason == "rate_limited"
    assert exc_info.value.retryable is True
    assert exc_info.value.retry_after_seconds == 900


@pytest.mark.anyio
async def test_selected_endpoint_retry_after_is_preserved_in_partial_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/status/logs/auth":
            return httpx.Response(429, headers={"Retry-After": "600"})
        if request.url.path == "/api/v2/status/system":
            return httpx.Response(200, json={"data": {"serial": "TEST"}})
        if request.url.path == "/api/v2/system/restapi/version":
            return httpx.Response(200, json={"data": {"current_version": "2.9.0"}})
        if request.url.path == "/api/v2/system/version":
            return httpx.Response(200, json={"data": {"version": "fixture"}})
        return httpx.Response(200, json={"data": []})

    client = PfRestV2Client(
        config(collect_security_logs=True), transport=httpx.MockTransport(handler)
    )
    try:
        snapshot = await client.read_snapshot()
    finally:
        await client.close()
    assert snapshot.endpoint_errors == {"log_auth": "rate_limited"}
    assert snapshot.endpoint_retry_after_seconds == {"log_auth": 600}


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

    assert exc_info.value.reason == "authentication_failed"
    assert exc_info.value.remediation == "reauthenticate"
    assert "secret-key" not in str(exc_info.value)


def test_insecure_transport_requires_config_and_deployment_lab_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_PFSENSE_LAB_ALLOW_INSECURE", raising=False)
    with pytest.raises(ValueError, match="allow_insecure_transport"):
        config(scheme="http", verify_tls=False)
    with pytest.raises(ValueError, match="disabled by the deployment"):
        config(
            scheme="http",
            port=80,
            verify_tls=False,
            allow_insecure_transport=True,
        )
    monkeypatch.setenv("PIPHI_PFSENSE_LAB_ALLOW_INSECURE", "true")
    insecure = config(
        scheme="http", port=80, verify_tls=False, allow_insecure_transport=True
    )
    assert insecure.base_url == "http://pfsense.test"


def test_custom_ca_is_confined_to_approved_mounts() -> None:
    for path in (
        "/tmp/router-ca.pem",
        "/etc/ssl/certs-evil/router-ca.pem",
        "/run/secrets/../outside/router-ca.pem",
        "run/secrets/router-ca.pem",
    ):
        with pytest.raises(ValueError, match="approved read-only"):
            config(ca_bundle_path=path)
    assert config(ca_bundle_path="/run/secrets/router-ca.pem").ca_bundle_path


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
