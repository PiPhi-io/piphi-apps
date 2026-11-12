from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from time import monotonic
from typing import Any, Protocol

import httpx

from .schemas import DeviceConfig


class PfSenseError(RuntimeError):
    """Safe, credential-free error returned by the pfSense transport."""


@dataclass(slots=True)
class PfSenseSnapshot:
    system: dict[str, Any]
    version: dict[str, Any] = field(default_factory=dict)
    api_version: dict[str, Any] = field(default_factory=dict)
    interfaces: list[dict[str, Any]] = field(default_factory=list)
    gateways: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    dhcp_leases: list[dict[str, Any]] = field(default_factory=list)
    arp_entries: list[dict[str, Any]] = field(default_factory=list)
    certificates: list[dict[str, Any]] = field(default_factory=list)
    carp: dict[str, Any] = field(default_factory=dict)
    virtual_ips: list[dict[str, Any]] = field(default_factory=list)
    ha_sync: dict[str, Any] = field(default_factory=dict)
    logs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    openvpn_clients: list[dict[str, Any]] = field(default_factory=list)
    openvpn_servers: list[dict[str, Any]] = field(default_factory=list)
    ipsec_sas: list[dict[str, Any]] = field(default_factory=list)
    wireguard_tunnels: list[dict[str, Any]] = field(default_factory=list)
    endpoint_errors: dict[str, str] = field(default_factory=dict)
    api_latency_ms: float = 0.0


class PfSenseClient(Protocol):
    async def read_snapshot(self) -> PfSenseSnapshot: ...

    async def diagnostic_ping(self, host: str, *, count: int) -> dict[str, Any]: ...

    async def restart_service(self, service_name: str) -> dict[str, Any]: ...

    async def start_service(self, service_name: str) -> dict[str, Any]: ...

    async def wake_on_lan(self, *, interface: str, mac_addr: str) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class PfRestV2Client:
    """Small async client for the community pfSense REST API v2."""

    def __init__(
        self,
        config: DeviceConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        verify: bool | str = config.ca_bundle_path or config.verify_tls
        self._collect_dhcp_leases = config.collect_dhcp_leases
        self._collect_vpn_status = config.collect_vpn_status
        self._collect_client_inventory = config.collect_client_inventory
        self._collect_security_logs = config.collect_security_logs
        self._collect_certificates = config.collect_certificates
        self._collect_ha_status = config.collect_ha_status
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "Accept": "application/json",
                "X-API-Key": config.secret_api_key(),
            },
            timeout=httpx.Timeout(15.0, connect=5.0),
            verify=verify,
            follow_redirects=False,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def read_snapshot(self) -> PfSenseSnapshot:
        started = monotonic()
        system = await self._get_object("/api/v2/status/system")

        requests: dict[str, Callable[[], Any]] = {
            "version": lambda: self._get_object("/api/v2/system/version"),
            "api_version": lambda: self._get_object("/api/v2/system/restapi/version"),
            "interfaces": lambda: self._get_list("/api/v2/status/interfaces"),
            "gateways": lambda: self._get_list("/api/v2/status/gateways"),
            "services": lambda: self._get_list("/api/v2/status/services"),
        }
        if self._collect_dhcp_leases or self._collect_client_inventory:
            requests["dhcp_leases"] = lambda: self._get_list(
                "/api/v2/status/dhcp_server/leases"
            )
        if self._collect_client_inventory:
            requests["arp_entries"] = lambda: self._get_list(
                "/api/v2/diagnostics/arp_table"
            )
        if self._collect_certificates:
            requests["certificates"] = lambda: self._get_list(
                "/api/v2/system/certificates"
            )
        if self._collect_ha_status:
            requests.update(
                {
                    "carp": lambda: self._get_object("/api/v2/status/carp"),
                    "virtual_ips": lambda: self._get_list(
                        "/api/v2/firewall/virtual_ips"
                    ),
                    "ha_sync": lambda: self._get_object("/api/v2/system/hasync"),
                }
            )
        if self._collect_security_logs:
            for log_name in ("firewall", "auth", "dhcp", "system"):
                requests[f"log_{log_name}"] = partial(
                    self._get_list, f"/api/v2/status/logs/{log_name}"
                )
        if self._collect_vpn_status:
            requests.update(
                {
                    "openvpn_clients": lambda: self._get_list(
                        "/api/v2/status/openvpn/clients"
                    ),
                    "openvpn_servers": lambda: self._get_list(
                        "/api/v2/status/openvpn/servers"
                    ),
                    "ipsec_sas": lambda: self._get_list("/api/v2/status/ipsec/sas"),
                    "wireguard_tunnels": lambda: self._get_list(
                        "/api/v2/status/wireguard/tunnels"
                    ),
                }
            )

        names = list(requests)
        results = await asyncio.gather(
            *(requests[name]() for name in names), return_exceptions=True
        )
        values: dict[str, Any] = {}
        endpoint_errors: dict[str, str] = {}
        for name, result in zip(names, results, strict=True):
            if isinstance(result, BaseException):
                endpoint_errors[name] = str(result)
            else:
                values[name] = result

        certificates = [
            {
                key: item.get(key)
                for key in (
                    "id",
                    "descr",
                    "refid",
                    "type",
                    "valid_from",
                    "valid_until",
                    "valid_days_left",
                )
            }
            for item in values.get("certificates", [])
        ]
        return PfSenseSnapshot(
            system=system,
            version=values.get("version", {}),
            api_version=values.get("api_version", {}),
            interfaces=values.get("interfaces", []),
            gateways=values.get("gateways", []),
            services=values.get("services", []),
            dhcp_leases=values.get("dhcp_leases", []),
            arp_entries=values.get("arp_entries", []),
            certificates=certificates,
            carp=values.get("carp", {}),
            virtual_ips=values.get("virtual_ips", []),
            ha_sync={
                key: values.get("ha_sync", {}).get(key)
                for key in ("pfsyncenabled", "pfsyncpeerip", "pfsyncinterface")
            },
            logs={
                name: values.get(f"log_{name}", [])
                for name in ("firewall", "auth", "dhcp", "system")
                if f"log_{name}" in values
            },
            openvpn_clients=values.get("openvpn_clients", []),
            openvpn_servers=values.get("openvpn_servers", []),
            ipsec_sas=values.get("ipsec_sas", []),
            wireguard_tunnels=values.get("wireguard_tunnels", []),
            endpoint_errors=endpoint_errors,
            api_latency_ms=round((monotonic() - started) * 1000, 2),
        )

    async def diagnostic_ping(self, host: str, *, count: int) -> dict[str, Any]:
        return await self._post_object(
            "/api/v2/diagnostics/ping", {"host": host, "count": count}
        )

    async def restart_service(self, service_name: str) -> dict[str, Any]:
        return await self._service_action(service_name, "restart")

    async def start_service(self, service_name: str) -> dict[str, Any]:
        return await self._service_action(service_name, "start")

    async def wake_on_lan(self, *, interface: str, mac_addr: str) -> dict[str, Any]:
        return await self._post_object(
            "/api/v2/services/wake_on_lan/send",
            {"interface": interface, "mac_addr": mac_addr},
        )

    async def _service_action(self, service_name: str, action: str) -> dict[str, Any]:
        services = await self._get_list("/api/v2/status/services")
        match = next(
            (
                service
                for service in services
                if str(service.get("name") or "").casefold() == service_name.casefold()
            ),
            None,
        )
        if match is None:
            raise PfSenseError(f"pfSense service is not available: {service_name}")
        service_id = match.get("id")
        if not isinstance(service_id, int):
            raise PfSenseError(
                f"pfSense returned no usable service ID for {service_name}"
            )
        return await self._post_object(
            "/api/v2/status/service",
            {"id": service_id, "action": action},
        )

    async def _get_object(self, path: str) -> dict[str, Any]:
        data = await self._get(path)
        if not isinstance(data, dict):
            raise PfSenseError(f"pfSense returned an invalid object for {path}")
        return data

    async def _get_list(self, path: str) -> list[dict[str, Any]]:
        data = await self._get(path)
        if not isinstance(data, list) or not all(
            isinstance(item, dict) for item in data
        ):
            raise PfSenseError(f"pfSense returned an invalid list for {path}")
        return data

    async def _post_object(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = await self._request("POST", path, payload=payload)
        if not isinstance(data, dict):
            raise PfSenseError(f"pfSense returned an invalid object for {path}")
        return data

    async def _get(self, path: str) -> Any:
        return await self._request("GET", path)

    async def _request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> Any:
        try:
            response = await self._client.request(method, path, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                raise PfSenseError(
                    f"pfSense denied {path} with HTTP {status}; check API-key privileges"
                ) from exc
            raise PfSenseError(f"pfSense returned HTTP {status} for {path}") from exc
        except httpx.RequestError as exc:
            raise PfSenseError(
                f"Unable to reach pfSense at {self._client.base_url}: {exc.__class__.__name__}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise PfSenseError(f"pfSense returned non-JSON data for {path}") from exc
        if not isinstance(payload, dict) or "data" not in payload:
            raise PfSenseError(f"pfSense returned an invalid API envelope for {path}")
        return payload["data"]
