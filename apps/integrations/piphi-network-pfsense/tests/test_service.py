from __future__ import annotations

import asyncio
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from piphi_network_pfsense.pfsense_client import PfSenseError, PfSenseSnapshot
from piphi_network_pfsense.schemas import DeviceConfig
from piphi_network_pfsense.service import (
    ActiveFirewall,
    PfSenseRuntimeService,
    _appliance_device_id,
    _opaque_child_id,
    _retry_delay,
    apply_interface_rates,
    main_metrics,
    snapshot_to_state,
)


def test_snapshot_is_normalized_into_firewall_state() -> None:
    state = snapshot_to_state(
        PfSenseSnapshot(
            system={
                "platform": "Netgate 6100",
                "cpu_usage": 15,
                "mem_usage": 42,
                "disk_usage": 21,
                "temp_c": 51.5,
                "uptime": "3 days",
            },
            version={"version": "25.11.1-RELEASE"},
            api_version={"current_version": "2.9.0", "update_available": False},
            interfaces=[
                {
                    "name": "wan",
                    "descr": "WAN",
                    "enable": True,
                    "status": "up",
                    "inbytes": 100,
                    "outbytes": 200,
                },
                {
                    "name": "lan",
                    "descr": "LAN",
                    "enable": True,
                    "status": "down",
                    "inerrs": 2,
                },
            ],
            gateways=[
                {"name": "WAN_DHCP", "status": "online", "delay": 12.5, "loss": 0},
                {"name": "BACKUP", "status": "down", "delay": 80, "loss": 100},
            ],
            services=[
                {"name": "unbound", "enabled": True, "status": True},
                {"name": "openvpn", "enabled": True, "status": False},
            ],
            dhcp_leases=[
                {
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "ip": "192.0.2.10",
                    "hostname": "office-pc",
                    "online_status": "online",
                },
                {"ip": "192.0.2.11", "online_status": "offline"},
            ],
            arp_entries=[
                {
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                    "ip_address": "192.0.2.10",
                    "interface": "lan",
                }
            ],
            certificates=[
                {
                    "refid": "cert-1",
                    "descr": "Web UI",
                    "valid_days_left": 7,
                    "crt": "must-not-leak",
                    "prv": "must-not-leak",
                }
            ],
            carp={"enable": True, "maintenance_mode": False},
            ha_sync={"pfsyncenabled": True},
            virtual_ips=[
                {
                    "uniqid": "vip-1",
                    "mode": "carp",
                    "descr": "WAN VIP",
                    "carp_status": "MASTER",
                    "password": "must-not-leak",
                }
            ],
            wireguard_tunnels=[{"name": "wg0", "status": "up"}],
            api_latency_ms=24.2,
        )
    )

    assert state["connected"] is True
    assert state["last_attempt_at"]
    assert state["last_success_at"]
    assert state["stale"] is False
    assert state["stale_age_seconds"] == 0
    assert "serial" not in state
    assert state["interfaces_up"] == 1
    assert state["gateways_online"] == 1
    assert state["gateways_offline"] == 1
    assert state["gateway_max_loss_percent"] == 100
    assert state["services_down"] == 1
    assert state["dhcp_online_lease_count"] == 1
    assert state["vpn_tunnels_up"] == 1
    assert state["vpn_tunnels"][0]["protocol"] == "wireguard"
    assert "public_key" not in state["vpn_tunnels"][0]
    assert state["client_count"] == 2
    assert state["clients_online"] == 1
    serialized_clients = str(state["clients"])
    assert "192.0.2." not in serialized_clients
    assert "office-pc" not in serialized_clients
    assert "aa:bb:cc:dd:ee:ff" not in serialized_clients
    assert "interface" not in serialized_clients
    assert (
        next(
            item
            for item in state["clients"]
            if item["id"] == _opaque_child_id("client", "aa:bb:cc:dd:ee:ff")
        )[
            "source"
        ]
        == "dhcp+arp"
    )
    assert state["certificates_expiring"] == 1
    assert "crt" not in state["certificates"][0]
    assert "prv" not in state["certificates"][0]
    assert state["carp_primary_count"] == 1
    assert "password" not in state["carp_vips"][0]
    assert main_metrics(state)["memory_usage_percent"] == 42


def test_interface_rates_handle_first_sample_and_counter_reset() -> None:
    interfaces = [{"name": "wan", "bytes_received": 200, "bytes_sent": 400}]
    counters = apply_interface_rates(interfaces, None, elapsed_seconds=None)
    assert interfaces[0]["receive_rate_bps"] == 0

    interfaces = [{"name": "wan", "bytes_received": 1200, "bytes_sent": 900}]
    counters = apply_interface_rates(interfaces, counters, elapsed_seconds=10)
    assert interfaces[0]["receive_rate_bps"] == 800
    assert interfaces[0]["transmit_rate_bps"] == 400

    interfaces = [{"name": "wan", "bytes_received": 20, "bytes_sent": 10}]
    apply_interface_rates(interfaces, counters, elapsed_seconds=10)
    assert interfaces[0]["receive_rate_bps"] == 0
    assert interfaces[0]["transmit_rate_bps"] == 0


def test_appliance_identity_is_stable_and_opaque() -> None:
    snapshot = PfSenseSnapshot(system={"serial": "RAW-SERIAL-123"})
    device_id = _appliance_device_id(snapshot)
    assert device_id == _appliance_device_id(snapshot)
    assert device_id.startswith("pfsense-")
    assert "RAW-SERIAL-123" not in device_id


class ActionClient:
    def __init__(self) -> None:
        self.pings: list[tuple[str, int]] = []
        self.restarts: list[str] = []
        self.starts: list[str] = []
        self.wakes: list[tuple[str, str]] = []

    async def read_snapshot(self) -> PfSenseSnapshot:
        return PfSenseSnapshot(system={})

    async def diagnostic_ping(self, host: str, *, count: int):
        self.pings.append((host, count))
        return {"result_code": 0, "output": "ok"}

    async def restart_service(self, service_name: str):
        self.restarts.append(service_name)
        return {"name": service_name, "status": True}

    async def start_service(self, service_name: str):
        self.starts.append(service_name)
        return {"name": service_name, "status": True}

    async def wake_on_lan(self, *, interface: str, mac_addr: str):
        self.wakes.append((interface, mac_addr))
        return {"interface": interface, "mac_addr": mac_addr}

    async def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_reconfigure_rejects_identity_change_without_replacing_session() -> None:
    config_id = "firewall-1"
    old_entry = {
        "config_id": config_id,
        "device_id": _appliance_device_id(
            PfSenseSnapshot(system={"serial": "ORIGINAL-SERIAL"})
        ),
    }

    class Registry:
        def __init__(self) -> None:
            self.entries = {config_id: old_entry}

        def get(self, key: str):
            return self.entries.get(key)

    class TrackingClient(ActionClient):
        def __init__(self, serial: str) -> None:
            super().__init__()
            self.serial = serial
            self.closed = False

        async def read_snapshot(self) -> PfSenseSnapshot:
            return PfSenseSnapshot(
                system={"serial": self.serial},
                api_version={"current_version": "2.9.0"},
            )

        async def close(self) -> None:
            self.closed = True

    registry = Registry()
    working_client = TrackingClient("ORIGINAL-SERIAL")
    replacement_client = TrackingClient("DIFFERENT-SERIAL")
    service = PfSenseRuntimeService(
        registry=registry,
        runtime=SimpleNamespace(),
        telemetry=SimpleNamespace(),
        client_factory=lambda _config: replacement_client,
    )
    working = ActiveFirewall(
        config=DeviceConfig(id=config_id, host="old.test", api_key="old-key"),
        entry=old_entry,
        client=working_client,
    )
    service._active[config_id] = working

    replacement = DeviceConfig(id=config_id, host="new.test", api_key="new-key")
    with pytest.raises(ValueError, match="different pfSense appliance"):
        await service.configure(replacement, {"config_id": config_id})

    assert registry.get(config_id) is old_entry
    assert service._active[config_id] is working
    assert working_client.closed is False
    assert replacement_client.closed is True


def action_service(config: DeviceConfig) -> tuple[PfSenseRuntimeService, ActionClient]:
    client = ActionClient()
    service = PfSenseRuntimeService(
        registry=SimpleNamespace(),
        runtime=SimpleNamespace(),
        telemetry=SimpleNamespace(),
    )
    service._active["firewall-1"] = ActiveFirewall(
        config=config,
        entry={"config_id": "firewall-1", "device_id": "firewall-1"},
        client=client,
    )
    return service, client


@pytest.mark.anyio
async def test_control_actions_require_opt_in_and_exact_allowlists() -> None:
    disabled, disabled_client = action_service(
        DeviceConfig(id="firewall-1", host="pfsense.test", api_key="key")
    )
    with pytest.raises(HTTPException) as ping_disabled:
        await disabled.diagnostic_ping("firewall-1", host="1.1.1.1", count=3)
    assert ping_disabled.value.status_code == 403
    assert disabled_client.pings == []

    enabled, client = action_service(
        DeviceConfig(
            id="firewall-1",
            host="pfsense.test",
            api_key="key",
            enable_diagnostic_ping=True,
            allowed_ping_hosts=["1.1.1.1"],
            enable_service_restart=True,
            enable_service_start=True,
            allowed_services=["telegraf"],
            enable_wake_on_lan=True,
            wake_on_lan_targets=[
                {
                    "id": "office-pc",
                    "label": "Office PC",
                    "interface": "lan",
                    "mac_addr": "AA-BB-CC-DD-EE-FF",
                }
            ],
        )
    )
    await enabled.diagnostic_ping("firewall-1", host="1.1.1.1", count=2)
    await enabled.restart_service("firewall-1", service_name="TELEGRAF")
    await enabled.start_service("firewall-1", service_name="Telegraf")
    wake = await enabled.wake_on_lan("firewall-1", target_id="OFFICE-PC")
    assert client.pings == [("1.1.1.1", 2)]
    assert client.restarts == ["telegraf"]
    assert client.starts == ["telegraf"]
    assert client.wakes == [("lan", "aa:bb:cc:dd:ee:ff")]
    assert wake["target_label"] == "Office PC"

    with pytest.raises(HTTPException) as target_denied:
        await enabled.diagnostic_ping("firewall-1", host="8.8.8.8", count=2)
    with pytest.raises(HTTPException) as service_denied:
        await enabled.restart_service("firewall-1", service_name="sshd")
    assert target_denied.value.status_code == 403
    assert service_denied.value.status_code == 403
    assert client.pings == [("1.1.1.1", 2)]
    assert client.restarts == ["telegraf"]


@pytest.mark.anyio
async def test_operations_are_serialized_per_firewall() -> None:
    service, client = action_service(
        DeviceConfig(
            id="firewall-1",
            host="pfsense.test",
            api_key="key",
            enable_diagnostic_ping=True,
            allowed_ping_hosts=["1.1.1.1"],
        )
    )
    in_flight = 0
    maximum = 0

    async def slow_ping(host: str, *, count: int):
        nonlocal in_flight, maximum
        in_flight += 1
        maximum = max(maximum, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return {"result_code": 0}

    client.diagnostic_ping = slow_ping  # type: ignore[method-assign]
    await asyncio.gather(
        service.diagnostic_ping("firewall-1", host="1.1.1.1", count=1),
        service.diagnostic_ping("firewall-1", host="1.1.1.1", count=1),
    )
    assert maximum == 1


def test_transition_events_are_emitted_only_for_changed_children(monkeypatch) -> None:
    events: list[dict] = []

    def capture(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(
        "piphi_network_pfsense.service.schedule_event_delivery", capture
    )
    service, client = action_service(
        DeviceConfig(id="firewall-1", host="pfsense.test", api_key="key")
    )
    service.event_client = object()
    service.runtime = SimpleNamespace(process_state=object(), auth=object())
    active = ActiveFirewall(
        config=DeviceConfig(id="firewall-1", host="pfsense.test", api_key="key"),
        entry={
            "config_id": "firewall-1",
            "device_id": "firewall-1",
            "integration_id": "piphi-network-pfsense",
        },
        client=client,
    )
    service._emit_transitions(
        active,
        {
            "gateways": [{"name": "WAN", "online": True}],
            "interfaces": [{"name": "wan", "up": True}],
            "services": [{"name": "unbound", "running": True}],
        },
        {
            "gateways": [{"name": "WAN", "online": False, "status": "down"}],
            "interfaces": [{"name": "wan", "up": True, "status": "up"}],
            "services": [{"name": "unbound", "running": False, "status": False}],
        },
    )
    assert [event["event_type"] for event in events] == [
        "network.gateway.offline",
        "network.service.stopped",
    ]
    assert events[0]["device"]["device_id"] == "firewall-1:gateway:WAN"


def test_log_deduplication_and_certificate_alert_levels(monkeypatch) -> None:
    events: list[dict] = []

    def capture(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(
        "piphi_network_pfsense.service.schedule_event_delivery", capture
    )
    service, client = action_service(
        DeviceConfig(id="firewall-1", host="pfsense.test", api_key="key")
    )
    service.event_client = object()
    service.runtime = SimpleNamespace(process_state=object(), auth=object())
    active = ActiveFirewall(
        config=DeviceConfig(id="firewall-1", host="pfsense.test", api_key="key"),
        entry={"config_id": "firewall-1", "device_id": "firewall-1"},
        client=client,
    )
    baseline = PfSenseSnapshot(
        system={}, logs={"auth": [{"text": "existing login failure"}]}
    )
    service._emit_log_events(active, baseline)
    service._emit_log_events(active, baseline)
    service._emit_log_events(
        active,
        PfSenseSnapshot(
            system={},
            logs={
                "auth": [
                    {"text": "existing login failure"},
                    {"text": "new login failure"},
                ]
            },
        ),
    )
    service._emit_certificate_alerts(
        active,
        {
            "certificates": [
                {
                    "id": "cert-1",
                    "description": "Web UI",
                    "days_remaining": 14,
                    "valid_until": "2026-09-19",
                }
            ]
        },
    )
    service._emit_certificate_alerts(
        active,
        {
            "certificates": [
                {
                    "id": "cert-1",
                    "description": "Web UI",
                    "days_remaining": 14,
                    "valid_until": "2026-09-19",
                }
            ]
        },
    )
    assert [event["event_type"] for event in events] == [
        "network.security.auth_log",
        "network.certificate.expiring",
    ]
    assert "message" not in events[0]["payload"]


def test_retryable_outage_recovers_but_permanent_failure_requires_action(
    monkeypatch,
) -> None:
    events: list[dict] = []
    states: list[dict] = []

    class Registry:
        def update_state(self, _config_id, state, **_kwargs):
            states.append(state)

    monkeypatch.setattr(
        "piphi_network_pfsense.service.schedule_event_delivery",
        lambda **kwargs: events.append(kwargs),
    )
    monkeypatch.setattr(
        "piphi_network_pfsense.service.schedule_telemetry_delivery",
        lambda **_kwargs: None,
    )
    client = ActionClient()
    service = PfSenseRuntimeService(
        registry=Registry(),
        runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(),
        event_client=object(),
    )
    snapshot = PfSenseSnapshot(
        system={"serial": "SERIAL-1"},
        api_version={"current_version": "2.9.0"},
    )
    device_id = _appliance_device_id(snapshot)
    active = ActiveFirewall(
        config=DeviceConfig(id="firewall-1", host="pfsense.test", api_key="key"),
        entry={"config_id": "firewall-1", "device_id": device_id},
        client=client,
        last_state={"connected": True, "last_success_at": "2026-01-01T00:00:00+00:00"},
    )

    assert service._mark_failure(
        active, PfSenseError("connection_failed", retryable=True, remediation="retry")
    )
    assert states[-1]["stale"] is True
    assert states[-1]["stale_age_seconds"] is not None
    assert [event["event_type"] for event in events] == ["network.appliance.offline"]

    service._apply_snapshot(active, snapshot)
    assert [event["event_type"] for event in events][-1] == (
        "network.appliance.recovered"
    )
    assert active.requires_user_action is False

    assert not service._mark_failure(
        active,
        PfSenseError(
            "authentication_failed",
            retryable=False,
            remediation="reauthenticate",
        ),
    )
    assert active.requires_user_action is True
    assert states[-1]["requires_user_action"] is True
    assert states[-1]["circuit_open"] is False


def test_five_retryable_failures_open_circuit_with_bounded_backoff_and_jitter(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "piphi_network_pfsense.service.schedule_telemetry_delivery",
        lambda **_kwargs: None,
    )
    service = PfSenseRuntimeService(
        registry=SimpleNamespace(update_state=lambda *_args, **_kwargs: None),
        runtime=SimpleNamespace(),
        telemetry=SimpleNamespace(),
    )
    active = ActiveFirewall(
        config=DeviceConfig(
            id="firewall-retry",
            host="pfsense.test",
            api_key="key",
            poll_interval_seconds=30,
        ),
        entry={"config_id": "firewall-retry", "device_id": "opaque-device"},
        client=ActionClient(),
    )
    delays = []
    for failure in range(1, 6):
        assert service._mark_failure(
            active,
            PfSenseError("connection_failed", retryable=True, remediation="retry"),
        )
        delays.append(_retry_delay(active))
        assert active.failure_count == failure
        assert (active.circuit_open_until > monotonic()) is (failure == 5)
    assert delays[:4] == sorted(delays[:4])
    assert all(1 <= delay <= 900 for delay in delays)
    assert 299 <= delays[-1] <= 300


def test_retry_after_is_honored_without_exceeding_backoff_bound() -> None:
    service = PfSenseRuntimeService(
        registry=SimpleNamespace(update_state=lambda *_args, **_kwargs: None),
        runtime=SimpleNamespace(),
        telemetry=SimpleNamespace(),
    )
    active = ActiveFirewall(
        config=DeviceConfig(id="limited", host="pfsense.test", api_key="key"),
        entry={"config_id": "limited", "device_id": "opaque-device"},
        client=ActionClient(),
    )
    service._mark_failure(
        active,
        PfSenseError(
            "rate_limited",
            retryable=True,
            remediation="retry",
            retry_after_seconds=1200,
        ),
    )
    assert _retry_delay(active) == 900


@pytest.mark.parametrize(
    "failure_reason", ["permission_denied", "endpoint_or_version_unsupported"]
)
def test_selected_endpoint_failure_is_unavailable_stale_and_actionable(
    monkeypatch, failure_reason,
) -> None:
    states: list[dict] = []
    telemetry_calls: list[dict] = []
    monkeypatch.setattr(
        "piphi_network_pfsense.service.schedule_telemetry_delivery",
        lambda **kwargs: telemetry_calls.append(kwargs),
    )
    service = PfSenseRuntimeService(
        registry=SimpleNamespace(
            update_state=lambda _config_id, state, **_kwargs: states.append(state)
        ),
        runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(),
    )
    prior = {
        "connected": True,
        "degraded": False,
        "last_success_at": "2026-01-01T00:00:00+00:00",
        "clients": [{"id": "opaque", "name": "Network client opaque", "online": True}],
    }
    active = ActiveFirewall(
        config=DeviceConfig(
            id="firewall-profile",
            host="pfsense.test",
            api_key="key",
            collect_client_inventory=True,
        ),
        entry={"config_id": "firewall-profile", "device_id": "opaque-device"},
        client=ActionClient(),
        last_state=prior,
        last_complete_state=prior,
    )
    state = service._apply_snapshot(
        active,
        PfSenseSnapshot(
            system={},
            api_version={"current_version": "2.9.0"},
            arp_entries=[{"mac_address": "aa:bb:cc:dd:ee:ff"}],
            endpoint_errors={"dhcp_leases": failure_reason},
        ),
    )
    assert state["connected"] is False
    assert state["degraded"] is True
    assert state["stale"] is True
    assert state["last_success_at"] == prior["last_success_at"]
    assert state["requires_user_action"] is True
    assert state["error"] == "selected_profile_unavailable"
    assert state["endpoint_errors"] == {"dhcp_leases": failure_reason}
    assert "clients" not in state
    assert state["last_known_good"] == {
        "stale": True,
        "observed_at": prior["last_success_at"],
        "values": {"clients": prior["clients"]},
    }
    assert telemetry_calls == []
    assert active.requires_user_action is True
    assert states[-1] is state


def test_transient_selected_endpoint_failure_remains_retryable_degraded_state(
    monkeypatch,
) -> None:
    telemetry_calls: list[dict] = []
    monkeypatch.setattr(
        "piphi_network_pfsense.service.schedule_telemetry_delivery",
        lambda **kwargs: telemetry_calls.append(kwargs),
    )
    service = PfSenseRuntimeService(
        registry=SimpleNamespace(update_state=lambda *_args, **_kwargs: None),
        runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(),
    )
    prior = {"connected": True, "last_success_at": "2026-01-01T00:00:00+00:00"}
    active = ActiveFirewall(
        config=DeviceConfig(
            id="firewall-profile",
            host="pfsense.test",
            api_key="key",
            collect_security_logs=True,
        ),
        entry={"config_id": "firewall-profile", "device_id": "opaque-device"},
        client=ActionClient(),
        last_state=prior,
        last_complete_state=prior,
    )
    state = service._apply_snapshot(
        active,
        PfSenseSnapshot(
            system={},
            api_version={"current_version": "2.9.0"},
            logs={"firewall": [{"event_id": "opaque-event"}]},
            endpoint_errors={"log_auth": "server_error"},
            endpoint_retry_after_seconds={"log_auth": 600},
        ),
    )
    assert state["connected"] is False
    assert state["degraded"] is True
    assert state["stale"] is True
    assert state["requires_user_action"] is False
    assert state["remediation"] == "retry"
    assert active.requires_user_action is False
    assert active.retry_after_seconds == 600
    assert telemetry_calls == []


@pytest.mark.anyio
async def test_permanent_selected_endpoint_denial_stops_polling_until_reconfigure(
    monkeypatch,
) -> None:
    async def no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr("piphi_network_pfsense.service.asyncio.sleep", no_wait)

    class DeniedProfileClient(ActionClient):
        calls = 0

        async def read_snapshot(self) -> PfSenseSnapshot:
            self.calls += 1
            return PfSenseSnapshot(
                system={},
                api_version={"current_version": "2.9.0"},
                endpoint_errors={"certificates": "permission_denied"},
            )

    client = DeniedProfileClient()
    config = DeviceConfig(
        id="firewall-profile",
        host="pfsense.test",
        api_key="key",
        collect_certificates=True,
    )
    active = ActiveFirewall(
        config=config,
        entry={"config_id": config.id, "device_id": "opaque-device"},
        client=client,
    )
    service = PfSenseRuntimeService(
        registry=SimpleNamespace(update_state=lambda *_args, **_kwargs: None),
        runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(),
    )
    service._active[config.id] = active

    await service._poll_loop(active)

    assert client.calls == 1
    assert active.requires_user_action is True
