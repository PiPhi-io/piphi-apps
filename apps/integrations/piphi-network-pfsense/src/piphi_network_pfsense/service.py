from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    schedule_event_delivery,
    schedule_telemetry_delivery,
)

from .pfsense_client import PfRestV2Client, PfSenseClient, PfSenseSnapshot
from .schemas import DeviceConfig
from .simulator import SimulatedPfSenseClient


@dataclass(slots=True)
class ActiveFirewall:
    config: DeviceConfig
    entry: dict[str, Any]
    client: PfSenseClient
    poll_task: asyncio.Task[None] | None = None
    previous_interface_counters: dict[str, tuple[int, int]] | None = None
    previous_observed_at: float | None = None
    last_state: dict[str, Any] | None = None
    seen_log_ids: set[str] | None = None
    certificate_alert_levels: dict[str, int] | None = None


ClientFactory = Callable[[DeviceConfig], PfSenseClient]


def default_client_factory(config: DeviceConfig) -> PfSenseClient:
    """Select only the transport; simulation and live share all projection logic."""
    if config.simulation_mode:
        return SimulatedPfSenseClient(config)
    return PfRestV2Client(config)


class PfSenseRuntimeService:
    """Owns reusable pfSense clients, polling tasks, and state projection."""

    def __init__(
        self,
        *,
        registry: Any,
        runtime: Any,
        telemetry: Any,
        event_client: Any | None = None,
        record_event: Callable[[dict[str, Any]], Any] | None = None,
        client_factory: ClientFactory = default_client_factory,
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.telemetry = telemetry
        self.event_client = event_client
        self.record_event = record_event
        self.client_factory = client_factory
        self._active: dict[str, ActiveFirewall] = {}
        self._lock = asyncio.Lock()

    @property
    def active_config_ids(self) -> list[str]:
        return list(self._active)

    async def configure(
        self, config: DeviceConfig, entry: dict[str, Any]
    ) -> dict[str, Any]:
        config_id = str(entry["config_id"])
        client = self.client_factory(config)
        try:
            snapshot = await client.read_snapshot()
        except Exception:
            await client.close()
            raise

        async with self._lock:
            previous = self._active.pop(config_id, None)
            if previous is not None:
                await self._stop(previous)
            active = ActiveFirewall(config=config, entry=entry, client=client)
            self._active[config_id] = active
            state = self._apply_snapshot(active, snapshot)
            active.poll_task = asyncio.create_task(
                self._poll_loop(active), name=f"pfsense-poller-{config_id}"
            )
            return state

    async def refresh(self, config_id: str) -> dict[str, Any]:
        active = self._active.get(str(config_id))
        if active is None:
            raise HTTPException(
                status_code=404, detail=f"unknown config_id={config_id}"
            )
        snapshot = await active.client.read_snapshot()
        return self._apply_snapshot(active, snapshot)

    async def diagnostic_ping(
        self, config_id: str, *, host: str, count: int
    ) -> dict[str, Any]:
        active = self._get_active(config_id)
        if not active.config.enable_diagnostic_ping:
            raise HTTPException(status_code=403, detail="diagnostic ping is disabled")
        allowed_host = _allowlisted_value(host, active.config.allowed_ping_hosts)
        if allowed_host is None:
            raise HTTPException(
                status_code=403,
                detail="ping target is not in allowed_ping_hosts",
            )
        if not 1 <= count <= 10:
            raise HTTPException(
                status_code=422, detail="ping count must be between 1 and 10"
            )
        return await active.client.diagnostic_ping(allowed_host, count=count)

    async def restart_service(
        self, config_id: str, *, service_name: str
    ) -> dict[str, Any]:
        active = self._get_active(config_id)
        if not active.config.enable_service_restart:
            raise HTTPException(status_code=403, detail="service restart is disabled")
        allowed_service = _allowlisted_value(
            service_name, active.config.allowed_services
        )
        if allowed_service is None:
            raise HTTPException(
                status_code=403,
                detail="service is not in allowed_services",
            )
        return await active.client.restart_service(allowed_service)

    async def start_service(
        self, config_id: str, *, service_name: str
    ) -> dict[str, Any]:
        active = self._get_active(config_id)
        if not active.config.enable_service_start:
            raise HTTPException(status_code=403, detail="service start is disabled")
        allowed_service = _allowlisted_value(
            service_name, active.config.allowed_services
        )
        if allowed_service is None:
            raise HTTPException(
                status_code=403, detail="service is not in allowed_services"
            )
        return await active.client.start_service(allowed_service)

    async def wake_on_lan(self, config_id: str, *, target_id: str) -> dict[str, Any]:
        active = self._get_active(config_id)
        if not active.config.enable_wake_on_lan:
            raise HTTPException(status_code=403, detail="Wake-on-LAN is disabled")
        requested = target_id.strip().casefold()
        target = next(
            (
                item
                for item in active.config.wake_on_lan_targets
                if item.id.casefold() == requested
            ),
            None,
        )
        if target is None:
            raise HTTPException(
                status_code=403, detail="target is not in wake_on_lan_targets"
            )
        result = await active.client.wake_on_lan(
            interface=target.interface, mac_addr=target.mac_addr
        )
        return {**result, "target_id": target.id, "target_label": target.label}

    def _get_active(self, config_id: str) -> ActiveFirewall:
        active = self._active.get(str(config_id))
        if active is None:
            raise HTTPException(
                status_code=404, detail=f"unknown config_id={config_id}"
            )
        return active

    async def remove(self, config_id: str) -> bool:
        async with self._lock:
            active = self._active.pop(str(config_id), None)
            if active is None:
                return False
            await self._stop(active)
            return True

    async def close(self) -> None:
        async with self._lock:
            active = list(self._active.values())
            self._active.clear()
            for session in active:
                await self._stop(session)

    async def _stop(self, active: ActiveFirewall) -> None:
        task = active.poll_task
        active.poll_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await active.client.close()

    async def _poll_loop(self, active: ActiveFirewall) -> None:
        while self._active.get(str(active.entry["config_id"])) is active:
            await asyncio.sleep(active.config.poll_interval_seconds)
            try:
                snapshot = await active.client.read_snapshot()
                self._apply_snapshot(active, snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- keep polling after transient API failures
                self.registry.update_state(
                    str(active.entry["config_id"]),
                    {
                        "connected": False,
                        "error": str(exc),
                        "last_attempt_at": _now(),
                    },
                    device_id=str(active.entry["device_id"]),
                )

    def _apply_snapshot(
        self, active: ActiveFirewall, snapshot: PfSenseSnapshot
    ) -> dict[str, Any]:
        state = snapshot_to_state(snapshot)
        observed_at = monotonic()
        counters = apply_interface_rates(
            state["interfaces"],
            active.previous_interface_counters,
            elapsed_seconds=(
                observed_at - active.previous_observed_at
                if active.previous_observed_at is not None
                else None
            ),
        )
        active.previous_interface_counters = counters
        active.previous_observed_at = observed_at
        config_id = str(active.entry["config_id"])
        device_id = str(active.entry["device_id"])
        if active.last_state is not None:
            self._emit_transitions(active, active.last_state, state)
        self._emit_certificate_alerts(active, state)
        self._emit_log_events(active, snapshot)
        active.last_state = state
        self.registry.update_state(config_id, state, device_id=device_id)
        _schedule_metrics(
            runtime=self.runtime,
            telemetry=self.telemetry,
            entry=active.entry,
            device_id=device_id,
            metrics=main_metrics(state),
            units=MAIN_UNITS,
        )
        for interface in state["interfaces"]:
            _schedule_metrics(
                runtime=self.runtime,
                telemetry=self.telemetry,
                entry=active.entry,
                device_id=f"{device_id}:interface:{interface['name']}",
                metrics={
                    "interface_up": interface["up"],
                    "bytes_received": interface["bytes_received"],
                    "bytes_sent": interface["bytes_sent"],
                    "errors_in": interface["errors_in"],
                    "errors_out": interface["errors_out"],
                    "receive_rate_bps": interface["receive_rate_bps"],
                    "transmit_rate_bps": interface["transmit_rate_bps"],
                },
                units=INTERFACE_UNITS,
            )
        for gateway in state["gateways"]:
            _schedule_metrics(
                runtime=self.runtime,
                telemetry=self.telemetry,
                entry=active.entry,
                device_id=f"{device_id}:gateway:{gateway['name']}",
                metrics={
                    "gateway_online": gateway["online"],
                    "gateway_latency_ms": gateway["latency_ms"],
                    "gateway_loss_percent": gateway["loss_percent"],
                },
                units=GATEWAY_UNITS,
            )
        for tunnel in state["vpn_tunnels"]:
            _schedule_metrics(
                runtime=self.runtime,
                telemetry=self.telemetry,
                entry=active.entry,
                device_id=(f"{device_id}:vpn:{tunnel['protocol']}:{tunnel['name']}"),
                metrics={
                    "vpn_connected": tunnel["connected"],
                    "vpn_bytes_received": tunnel["bytes_received"],
                    "vpn_bytes_sent": tunnel["bytes_sent"],
                    "vpn_peer_count": tunnel["peer_count"],
                },
                units=VPN_UNITS,
            )
        for client in state["clients"]:
            _schedule_metrics(
                runtime=self.runtime,
                telemetry=self.telemetry,
                entry=active.entry,
                device_id=f"{device_id}:client:{client['id']}",
                metrics={"client_online": client["online"]},
                units=CLIENT_UNITS,
            )
        for certificate in state["certificates"]:
            _schedule_metrics(
                runtime=self.runtime,
                telemetry=self.telemetry,
                entry=active.entry,
                device_id=f"{device_id}:certificate:{certificate['id']}",
                metrics={"certificate_days_remaining": certificate["days_remaining"]},
                units=CERTIFICATE_UNITS,
            )
        for carp_vip in state["carp_vips"]:
            _schedule_metrics(
                runtime=self.runtime,
                telemetry=self.telemetry,
                entry=active.entry,
                device_id=f"{device_id}:carp:{carp_vip['id']}",
                metrics={"carp_primary": carp_vip["primary"]},
                units=CARP_UNITS,
            )
        return state

    def _emit_transitions(
        self,
        active: ActiveFirewall,
        previous: dict[str, Any],
        current: dict[str, Any],
    ) -> None:
        transition_sets = (
            ("gateways", "online", "network.gateway.online", "network.gateway.offline"),
            ("interfaces", "up", "network.interface.up", "network.interface.down"),
            (
                "services",
                "running",
                "network.service.recovered",
                "network.service.stopped",
            ),
            ("clients", "online", "network.client.online", "network.client.offline"),
        )
        for collection, field, positive_event, negative_event in transition_sets:
            old = {
                str(item["name"]): bool(item[field])
                for item in previous.get(collection, [])
            }
            for item in current.get(collection, []):
                name = str(item["name"])
                value = bool(item[field])
                if name not in old or old[name] == value:
                    continue
                self._schedule_event(
                    active,
                    event_type=positive_event if value else negative_event,
                    child_kind=collection[:-1],
                    name=name,
                    payload={"name": name, field: value, "status": item.get("status")},
                    severity="info" if value else "warning",
                )
        previous_clients = {str(item["id"]) for item in previous.get("clients", [])}
        current_clients = {str(item["id"]): item for item in current.get("clients", [])}
        for prior in previous.get("clients", []):
            prior_id = str(prior["id"])
            if prior.get("online") and prior_id not in current_clients:
                self._schedule_event(
                    active,
                    event_type="network.client.offline",
                    child_kind="client",
                    name=prior_id,
                    payload={"id": prior_id, "online": False},
                    severity="warning",
                )
        for client in current.get("clients", []):
            if str(client["id"]) not in previous_clients:
                self._schedule_event(
                    active,
                    event_type="network.client.discovered",
                    child_kind="client",
                    name=str(client["id"]),
                    payload={
                        "id": client["id"],
                        "hostname": client.get("hostname"),
                        "ip_address": client.get("ip_address"),
                        "interface": client.get("interface"),
                    },
                    severity="info",
                )
        old_carp = {
            str(item["id"]): item["status"] for item in previous.get("carp_vips", [])
        }
        for vip in current.get("carp_vips", []):
            vip_id = str(vip["id"])
            if vip_id in old_carp and old_carp[vip_id] != vip["status"]:
                self._schedule_event(
                    active,
                    event_type="network.ha.role_changed",
                    child_kind="carp",
                    name=vip_id,
                    payload={"id": vip_id, "status": vip["status"]},
                    severity="warning",
                )

    def _emit_certificate_alerts(
        self, active: ActiveFirewall, state: dict[str, Any]
    ) -> None:
        levels = active.certificate_alert_levels
        if levels is None:
            levels = {}
            active.certificate_alert_levels = levels
        for certificate in state["certificates"]:
            days = _integer(certificate["days_remaining"])
            level = next(
                (threshold for threshold in (0, 1, 7, 14, 30) if days <= threshold),
                31,
            )
            certificate_id = str(certificate["id"])
            if level > 30 or (
                certificate_id in levels and levels[certificate_id] <= level
            ):
                continue
            levels[certificate_id] = level
            self._schedule_event(
                active,
                event_type=(
                    "network.certificate.expired"
                    if days <= 0
                    else "network.certificate.expiring"
                ),
                child_kind="certificate",
                name=certificate_id,
                payload={
                    "id": certificate_id,
                    "description": certificate.get("description"),
                    "days_remaining": days,
                    "valid_until": certificate.get("valid_until"),
                },
                severity="error" if days <= 0 else "warning",
            )

    def _emit_log_events(
        self, active: ActiveFirewall, snapshot: PfSenseSnapshot
    ) -> None:
        current: dict[str, tuple[str, str]] = {}
        for stream, records in snapshot.logs.items():
            for record in records:
                message = str(record.get("text") or "").strip()
                if not message:
                    continue
                digest = sha256(f"{stream}\0{message}".encode()).hexdigest()
                current[digest] = (stream, message)
        if active.seen_log_ids is None:
            active.seen_log_ids = set(current)
            return
        event_types = {
            "firewall": "network.security.firewall_log",
            "auth": "network.security.auth_log",
            "dhcp": "network.client.dhcp_event",
            "system": "network.system.log_event",
        }
        for digest, (stream, message) in current.items():
            if digest in active.seen_log_ids:
                continue
            self._schedule_event(
                active,
                event_type=event_types[stream],
                child_kind="log",
                name=stream,
                payload={"stream": stream, "message": message[:1024]},
                severity="warning" if stream in {"firewall", "auth"} else "info",
            )
        active.seen_log_ids.update(current)
        if len(active.seen_log_ids) > 4096:
            active.seen_log_ids = set(current)

    def _schedule_event(
        self,
        active: ActiveFirewall,
        *,
        event_type: str,
        child_kind: str,
        name: str,
        payload: dict[str, Any],
        severity: str,
    ) -> None:
        if self.event_client is None:
            return
        device = {
            **active.entry,
            "device_id": f"{active.entry['device_id']}:{child_kind}:{name}",
            "parent_device_id": active.entry["device_id"],
        }
        schedule_event_delivery(
            process_state=self.runtime.process_state,
            event_client=self.event_client,
            auth_context=self.runtime.auth,
            event_type=event_type,
            device=device,
            payload=payload,
            source="piphi-network-pfsense",
            severity=severity,
            record_event=self.record_event,
        )


def snapshot_to_state(snapshot: PfSenseSnapshot) -> dict[str, Any]:
    interfaces = [
        {
            "name": str(
                item.get("name") or item.get("descr") or item.get("id") or "unknown"
            ),
            "description": item.get("descr"),
            "status": item.get("status"),
            "up": _status_is_up(item.get("status")) and bool(item.get("enable", True)),
            "ipv4_address": item.get("ipaddr"),
            "ipv6_address": item.get("ipaddrv6"),
            "media": item.get("media"),
            "bytes_received": _integer(item.get("inbytes")),
            "bytes_sent": _integer(item.get("outbytes")),
            "errors_in": _integer(item.get("inerrs")),
            "errors_out": _integer(item.get("outerrs")),
        }
        for item in snapshot.interfaces
    ]
    gateways = [
        {
            "name": str(item.get("name") or item.get("id") or "unknown"),
            "status": item.get("status"),
            "online": _status_is_up(item.get("status")),
            "latency_ms": _number(item.get("delay")),
            "loss_percent": _number(item.get("loss")),
            "monitor_ip": item.get("monitorip"),
        }
        for item in snapshot.gateways
    ]
    services = [
        {
            "name": str(item.get("name") or item.get("id") or "unknown"),
            "description": item.get("description"),
            "enabled": item.get("enabled"),
            "running": bool(item.get("status")),
        }
        for item in snapshot.services
    ]
    vpn_tunnels = _vpn_tunnels(snapshot)
    vpn = _vpn_summary(snapshot, vpn_tunnels)
    clients = _network_clients(snapshot)
    certificates = _certificates(snapshot)
    carp_vips = _carp_vips(snapshot)
    online_leases = sum(
        1
        for lease in snapshot.dhcp_leases
        if str(lease.get("online_status") or "").lower() in {"online", "active"}
    )
    return {
        "connected": True,
        "last_success_at": _now(),
        "error": None,
        "api_latency_ms": snapshot.api_latency_ms,
        "platform": snapshot.system.get("platform"),
        "serial": snapshot.system.get("serial"),
        "uptime": snapshot.system.get("uptime"),
        "pfsense_version": snapshot.version.get("version"),
        "rest_api_version": snapshot.api_version.get("current_version"),
        "rest_api_update_available": snapshot.api_version.get("update_available"),
        "cpu_usage_percent": _number(snapshot.system.get("cpu_usage")),
        "memory_usage_percent": _number(snapshot.system.get("mem_usage")),
        "disk_usage_percent": _number(snapshot.system.get("disk_usage")),
        "swap_usage_percent": _number(snapshot.system.get("swap_usage")),
        "mbuf_usage_percent": _number(snapshot.system.get("mbuf_usage")),
        "temperature_c": _number(snapshot.system.get("temp_c")),
        "interface_count": len(interfaces),
        "interfaces_up": sum(1 for item in interfaces if item["up"]),
        "gateway_count": len(gateways),
        "gateways_online": sum(1 for item in gateways if item["online"]),
        "gateways_offline": sum(1 for item in gateways if not item["online"]),
        "gateway_max_latency_ms": max(
            (_number(item["latency_ms"]) for item in gateways), default=0.0
        ),
        "gateway_max_loss_percent": max(
            (_number(item["loss_percent"]) for item in gateways), default=0.0
        ),
        "service_count": len(services),
        "services_running": sum(1 for item in services if item["running"]),
        "services_down": sum(
            1 for item in services if item["enabled"] and not item["running"]
        ),
        "dhcp_lease_count": len(snapshot.dhcp_leases),
        "dhcp_online_lease_count": online_leases,
        "client_count": len(clients),
        "clients_online": sum(1 for item in clients if item["online"]),
        "certificate_count": len(certificates),
        "certificates_expiring": sum(
            1 for item in certificates if 0 < item["days_remaining"] <= 30
        ),
        "certificates_expired": sum(
            1 for item in certificates if item["days_remaining"] <= 0
        ),
        "ha_enabled": bool(snapshot.carp.get("enable")),
        "ha_maintenance_mode": bool(snapshot.carp.get("maintenance_mode")),
        "ha_sync_enabled": bool(snapshot.ha_sync.get("pfsyncenabled")),
        "carp_vip_count": len(carp_vips),
        "carp_primary_count": sum(1 for item in carp_vips if item["primary"]),
        "security_log_count": sum(len(items) for items in snapshot.logs.values()),
        **vpn,
        "interfaces": interfaces,
        "gateways": gateways,
        "services": services,
        "vpn_tunnels": vpn_tunnels,
        "clients": clients,
        "certificates": certificates,
        "carp_vips": carp_vips,
        "endpoint_errors": snapshot.endpoint_errors,
    }


def _network_clients(snapshot: PfSenseSnapshot) -> list[dict[str, Any]]:
    clients: dict[str, dict[str, Any]] = {}
    for lease in snapshot.dhcp_leases:
        mac = str(lease.get("mac") or "").strip().lower()
        ip = str(lease.get("ip") or "").strip()
        client_id = mac or ip
        if not client_id:
            continue
        online_status = str(lease.get("online_status") or "").lower()
        clients[client_id] = {
            "id": client_id,
            "name": str(lease.get("hostname") or lease.get("descr") or ip or client_id),
            "hostname": lease.get("hostname"),
            "ip_address": ip or None,
            "mac_address": mac or None,
            "interface": lease.get("if"),
            "online": online_status in {"online", "active"},
            "lease_ends": lease.get("ends"),
            "source": "dhcp",
        }
    for arp in snapshot.arp_entries:
        mac = str(arp.get("mac_address") or "").strip().lower()
        ip = str(arp.get("ip_address") or "").strip()
        client_id = mac or ip
        if not client_id:
            continue
        existing = clients.get(client_id, {})
        hostname = (
            existing.get("hostname") or arp.get("hostname") or arp.get("dnsresolve")
        )
        clients[client_id] = {
            **existing,
            "id": client_id,
            "name": str(hostname or ip or client_id),
            "hostname": hostname,
            "ip_address": ip or existing.get("ip_address"),
            "mac_address": mac or existing.get("mac_address"),
            "interface": arp.get("interface") or existing.get("interface"),
            "online": True,
            "source": "dhcp+arp" if existing else "arp",
        }
    return sorted(clients.values(), key=lambda item: str(item["id"]))


def _certificates(snapshot: PfSenseSnapshot) -> list[dict[str, Any]]:
    certificates = []
    for index, item in enumerate(snapshot.certificates):
        certificate_id = item.get("refid") or item.get("id") or f"certificate-{index}"
        raw_days_remaining = item.get("valid_days_left")
        certificates.append(
            {
                "id": str(certificate_id),
                "name": str(item.get("descr") or certificate_id),
                "description": item.get("descr"),
                "type": item.get("type"),
                "valid_from": item.get("valid_from"),
                "valid_until": item.get("valid_until"),
                "days_remaining": (
                    _integer(raw_days_remaining)
                    if raw_days_remaining is not None
                    else 12000
                ),
                "expiry_known": raw_days_remaining is not None,
            }
        )
    return certificates


def _carp_vips(snapshot: PfSenseSnapshot) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(snapshot.virtual_ips):
        if str(item.get("mode") or "").lower() != "carp":
            continue
        vip_id = item.get("uniqid") or item.get("vhid") or f"vip-{index}"
        status = str(item.get("carp_status") or "unknown")
        result.append(
            {
                "id": str(vip_id),
                "name": str(item.get("descr") or item.get("subnet") or vip_id),
                "interface": item.get("interface"),
                "address": item.get("subnet"),
                "status": status,
                "primary": status.strip().lower() in {"master", "primary"},
            }
        )
    return result


def apply_interface_rates(
    interfaces: list[dict[str, Any]],
    previous: dict[str, tuple[int, int]] | None,
    *,
    elapsed_seconds: float | None,
) -> dict[str, tuple[int, int]]:
    """Attach counter-derived bit rates and return counters for the next sample."""
    current: dict[str, tuple[int, int]] = {}
    usable_elapsed = (
        elapsed_seconds if elapsed_seconds and elapsed_seconds > 0 else None
    )
    for interface in interfaces:
        name = str(interface["name"])
        received = _integer(interface["bytes_received"])
        sent = _integer(interface["bytes_sent"])
        current[name] = (received, sent)
        prior = previous.get(name) if previous else None
        if prior is None or usable_elapsed is None:
            interface["receive_rate_bps"] = 0.0
            interface["transmit_rate_bps"] = 0.0
            continue
        interface["receive_rate_bps"] = round(
            max(0, received - prior[0]) * 8 / usable_elapsed, 2
        )
        interface["transmit_rate_bps"] = round(
            max(0, sent - prior[1]) * 8 / usable_elapsed, 2
        )
    return current


def main_metrics(state: dict[str, Any]) -> dict[str, bool | int | float]:
    return {
        key: value
        for key, value in state.items()
        if key in MAIN_UNITS or key == "connected"
        if isinstance(value, (bool, int, float))
    }


def _schedule_metrics(
    *,
    runtime: Any,
    telemetry: Any,
    entry: dict[str, Any],
    device_id: str,
    metrics: dict[str, Any],
    units: dict[str, str],
) -> None:
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=device_id,
        container_id=entry.get("container_id"),
        metrics=metrics,
        units=units,
    )


def _vpn_summary(
    snapshot: PfSenseSnapshot, tunnels: list[dict[str, Any]]
) -> dict[str, int]:
    openvpn_server_connections = sum(
        len(item.get("conns") or []) for item in snapshot.openvpn_servers
    )
    return {
        "vpn_tunnel_count": len(tunnels),
        "vpn_tunnels_up": sum(1 for item in tunnels if item["connected"]),
        "openvpn_server_connections": openvpn_server_connections,
    }


def _vpn_tunnels(snapshot: PfSenseSnapshot) -> list[dict[str, Any]]:
    tunnels: list[dict[str, Any]] = []
    for index, item in enumerate(snapshot.openvpn_clients):
        tunnels.append(
            _vpn_tunnel(
                item,
                protocol="openvpn",
                name=item.get("name") or item.get("vpnid") or f"client-{index}",
                status=item.get("state") or item.get("status"),
                remote_endpoint=item.get("remote_host"),
            )
        )
    for index, item in enumerate(snapshot.ipsec_sas):
        child_sas = item.get("child_sas") or []
        tunnels.append(
            _vpn_tunnel(
                item,
                protocol="ipsec",
                name=item.get("con_id") or item.get("uniqueid") or f"sa-{index}",
                status=item.get("state"),
                remote_endpoint=item.get("remote_host"),
                bytes_received=sum(_integer(sa.get("bytes_in")) for sa in child_sas),
                bytes_sent=sum(_integer(sa.get("bytes_out")) for sa in child_sas),
                peer_count=len(child_sas),
            )
        )
    for index, item in enumerate(snapshot.wireguard_tunnels):
        tunnels.append(
            _vpn_tunnel(
                item,
                protocol="wireguard",
                name=item.get("name") or item.get("descr") or f"tunnel-{index}",
                status=item.get("status"),
                bytes_received=_integer(item.get("transfer_rx")),
                bytes_sent=_integer(item.get("transfer_tx")),
                peer_count=len(item.get("peers") or []),
            )
        )
    return tunnels


def _vpn_tunnel(
    item: dict[str, Any],
    *,
    protocol: str,
    name: Any,
    status: Any,
    remote_endpoint: Any = None,
    bytes_received: int = 0,
    bytes_sent: int = 0,
    peer_count: int = 0,
) -> dict[str, Any]:
    return {
        "name": str(name),
        "description": item.get("descr"),
        "protocol": protocol,
        "status": status,
        "connected": _status_is_up(status),
        "remote_endpoint": remote_endpoint,
        "bytes_received": bytes_received,
        "bytes_sent": bytes_sent,
        "peer_count": peer_count,
    }


def _status_is_up(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "up",
        "online",
        "connected",
        "established",
        "running",
    }


def _allowlisted_value(value: str, allowed: list[str]) -> str | None:
    requested = value.strip().casefold()
    return next((item for item in allowed if item.casefold() == requested), None)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


MAIN_UNITS = {
    "api_latency_ms": "ms",
    "cpu_usage_percent": "%",
    "memory_usage_percent": "%",
    "disk_usage_percent": "%",
    "swap_usage_percent": "%",
    "mbuf_usage_percent": "%",
    "temperature_c": "C",
    "interface_count": "interfaces",
    "interfaces_up": "interfaces",
    "gateway_count": "gateways",
    "gateways_online": "gateways",
    "gateways_offline": "gateways",
    "gateway_max_latency_ms": "ms",
    "gateway_max_loss_percent": "%",
    "service_count": "services",
    "services_running": "services",
    "services_down": "services",
    "dhcp_lease_count": "leases",
    "dhcp_online_lease_count": "leases",
    "vpn_tunnel_count": "tunnels",
    "vpn_tunnels_up": "tunnels",
    "openvpn_server_connections": "connections",
    "client_count": "clients",
    "clients_online": "clients",
    "certificate_count": "certificates",
    "certificates_expiring": "certificates",
    "certificates_expired": "certificates",
    "ha_enabled": "bool",
    "ha_maintenance_mode": "bool",
    "ha_sync_enabled": "bool",
    "carp_vip_count": "virtual IPs",
    "carp_primary_count": "virtual IPs",
    "security_log_count": "entries",
}

INTERFACE_UNITS = {
    "interface_up": "bool",
    "bytes_received": "bytes",
    "bytes_sent": "bytes",
    "errors_in": "errors",
    "errors_out": "errors",
    "receive_rate_bps": "bit/s",
    "transmit_rate_bps": "bit/s",
}

VPN_UNITS = {
    "vpn_connected": "bool",
    "vpn_bytes_received": "bytes",
    "vpn_bytes_sent": "bytes",
    "vpn_peer_count": "peers",
}

CLIENT_UNITS = {"client_online": "bool"}
CERTIFICATE_UNITS = {"certificate_days_remaining": "days"}
CARP_UNITS = {"carp_primary": "bool"}

GATEWAY_UNITS = {
    "gateway_online": "bool",
    "gateway_latency_ms": "ms",
    "gateway_loss_percent": "%",
}
