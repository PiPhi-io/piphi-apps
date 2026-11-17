from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from piphi_network_pfsense.pfsense_client import PfSenseSnapshot
from piphi_network_pfsense.schemas import DeviceConfig
from piphi_network_pfsense.service import (
    ActiveFirewall,
    PfSenseRuntimeService,
    _appliance_device_id,
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
    assert (
        next(item for item in state["clients"] if item["id"] == "aa:bb:cc:dd:ee:ff")[
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
            allowed_services=["unbound"],
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
    await enabled.restart_service("firewall-1", service_name="UNBOUND")
    await enabled.start_service("firewall-1", service_name="Unbound")
    wake = await enabled.wake_on_lan("firewall-1", target_id="OFFICE-PC")
    assert client.pings == [("1.1.1.1", 2)]
    assert client.restarts == ["unbound"]
    assert client.starts == ["unbound"]
    assert client.wakes == [("lan", "aa:bb:cc:dd:ee:ff")]
    assert wake["target_label"] == "Office PC"

    with pytest.raises(HTTPException) as target_denied:
        await enabled.diagnostic_ping("firewall-1", host="8.8.8.8", count=2)
    with pytest.raises(HTTPException) as service_denied:
        await enabled.restart_service("firewall-1", service_name="sshd")
    assert target_denied.value.status_code == 403
    assert service_denied.value.status_code == 403
    assert client.pings == [("1.1.1.1", 2)]
    assert client.restarts == ["unbound"]


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
