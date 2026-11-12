from __future__ import annotations

from typing import Any

from .pfsense_client import PfSenseSnapshot
from .schemas import DeviceConfig


class SimulatedPfSenseClient:
    """Deterministic pfREST-compatible transport for dashboard and flow testing."""

    def __init__(self, _config: DeviceConfig) -> None:
        self._sample = 0

    async def read_snapshot(self) -> PfSenseSnapshot:
        self._sample += 1
        received = 18_400_000 + self._sample * 72_000
        sent = 6_200_000 + self._sample * 24_000
        return PfSenseSnapshot(
            system={
                "platform": "Netgate 6100 (simulated)",
                "serial": "SIM-PFSENSE-01",
                "cpu_usage": 18,
                "mem_usage": 46,
                "disk_usage": 31,
                "swap_usage": 2,
                "mbuf_usage": 11,
                "temp_c": 47.5,
                "uptime": "12 days, 7 hours",
            },
            version={"version": "2.8.1-RELEASE"},
            api_version={"current_version": "2.9.0", "update_available": False},
            interfaces=[
                {
                    "name": "wan",
                    "descr": "WAN",
                    "enable": True,
                    "status": "up",
                    "inbytes": received,
                    "outbytes": sent,
                    "inerrs": 0,
                    "outerrs": 0,
                },
                {
                    "name": "lan",
                    "descr": "Home LAN",
                    "enable": True,
                    "status": "up",
                    "inbytes": sent,
                    "outbytes": received,
                    "inerrs": 0,
                    "outerrs": 0,
                },
            ],
            gateways=[
                {"name": "WAN_DHCP", "status": "online", "delay": 11.8, "loss": 0},
                {"name": "LTE_BACKUP", "status": "online", "delay": 36.2, "loss": 0.4},
            ],
            services=[
                {"id": 1, "name": "unbound", "enabled": True, "status": True},
                {"id": 2, "name": "openvpn", "enabled": True, "status": True},
                {"id": 3, "name": "ntpd", "enabled": True, "status": True},
            ],
            dhcp_leases=[
                {
                    "mac": "02:00:00:00:00:01",
                    "ip": "192.168.1.20",
                    "hostname": "living-room-tv",
                    "if": "lan",
                    "online_status": "online",
                },
                {
                    "mac": "02:00:00:00:00:02",
                    "ip": "192.168.1.31",
                    "hostname": "office-laptop",
                    "if": "lan",
                    "online_status": "online",
                },
                {
                    "mac": "02:00:00:00:00:03",
                    "ip": "192.168.1.44",
                    "hostname": "guest-phone",
                    "if": "lan",
                    "online_status": "offline",
                },
            ],
            arp_entries=[
                {
                    "mac_address": "02:00:00:00:00:01",
                    "ip_address": "192.168.1.20",
                    "hostname": "living-room-tv",
                    "interface": "lan",
                },
                {
                    "mac_address": "02:00:00:00:00:02",
                    "ip_address": "192.168.1.31",
                    "hostname": "office-laptop",
                    "interface": "lan",
                },
            ],
            certificates=[
                {
                    "refid": "web-ui",
                    "descr": "Firewall Web UI",
                    "type": "server",
                    "valid_days_left": 87,
                },
                {
                    "refid": "vpn-client",
                    "descr": "Remote access VPN",
                    "type": "server",
                    "valid_days_left": 19,
                },
            ],
            carp={"enable": True, "maintenance_mode": False},
            virtual_ips=[
                {
                    "uniqid": "home-vip",
                    "mode": "carp",
                    "descr": "Home gateway",
                    "interface": "wan",
                    "subnet": "192.0.2.2",
                    "carp_status": "MASTER",
                }
            ],
            ha_sync={
                "pfsyncenabled": True,
                "pfsyncpeerip": "192.0.2.3",
                "pfsyncinterface": "sync",
            },
            logs={
                "firewall": [
                    {"id": "sim-fw-1", "text": "Blocked unsolicited inbound connection"}
                ],
                "auth": [{"id": "sim-auth-1", "text": "Administrator login succeeded"}],
            },
            openvpn_clients=[
                {
                    "name": "remote-office",
                    "descr": "Remote office",
                    "state": "connected",
                    "remote_host": "198.51.100.22",
                }
            ],
            wireguard_tunnels=[
                {
                    "name": "mobile",
                    "descr": "Mobile access",
                    "status": "up",
                    "transfer_rx": 820_000,
                    "transfer_tx": 410_000,
                    "peers": [{"name": "phone"}],
                }
            ],
            api_latency_ms=8.4,
        )

    async def diagnostic_ping(self, host: str, *, count: int) -> dict[str, Any]:
        return {
            "host": host,
            "result_code": 0,
            "output": f"{count} packets transmitted, {count} received",
        }

    async def restart_service(self, service_name: str) -> dict[str, Any]:
        return {"name": service_name, "status": True, "simulated": True}

    async def start_service(self, service_name: str) -> dict[str, Any]:
        return {"name": service_name, "status": True, "simulated": True}

    async def wake_on_lan(self, *, interface: str, mac_addr: str) -> dict[str, Any]:
        return {
            "interface": interface,
            "mac_addr": mac_addr,
            "sent": True,
            "simulated": True,
        }

    async def close(self) -> None:
        return None
