from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from time import monotonic
from typing import Any, Protocol

import httpx

from .schemas import DeviceConfig

MAX_RESPONSE_BYTES = 1_048_576
MAX_ROWS = 1_000
MAX_LOG_ROWS = 200
MAX_ENDPOINT_CONCURRENCY = 4


class PfSenseError(RuntimeError):
    """Safe, credential-free and actionable pfREST failure."""

    def __init__(
        self,
        reason: str,
        *,
        retryable: bool = False,
        remediation: str = "reconfigure",
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.remediation = remediation


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
        self._endpoint_slots = asyncio.Semaphore(MAX_ENDPOINT_CONCURRENCY)
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
                    self._get_log_rows, f"/api/v2/status/logs/{log_name}"
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
        failures: dict[str, BaseException] = {}
        for name, result in zip(names, results, strict=True):
            if isinstance(result, BaseException):
                failures[name] = result
                endpoint_errors[name] = (
                    result.reason
                    if isinstance(result, PfSenseError)
                    else "invalid_response"
                )
            else:
                values[name] = result

        essential = {"version", "api_version", "interfaces", "gateways", "services"}
        denied_or_invalid = sorted(essential & endpoint_errors.keys())
        if denied_or_invalid:
            errors = [failures[name] for name in denied_or_invalid]
            permanent = next(
                (
                    error
                    for error in errors
                    if not isinstance(error, PfSenseError) or not error.retryable
                ),
                None,
            )
            selected = permanent or errors[0]
            raise PfSenseError(
                "pfSense baseline profile is unavailable: "
                + ", ".join(denied_or_invalid),
                retryable=isinstance(selected, PfSenseError) and selected.retryable,
                remediation=(
                    selected.remediation
                    if isinstance(selected, PfSenseError)
                    else "reconfigure"
                ),
            )

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
        if len(data) > MAX_ROWS:
            raise PfSenseError("response_row_limit_exceeded")
        return data

    async def _get_log_rows(self, path: str) -> list[dict[str, Any]]:
        data = await self._get_list(path)
        return [_structured_log_record(item) for item in data[:MAX_LOG_ROWS]]

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
        response: httpx.Response | None = None
        try:
            async with self._endpoint_slots:
                request = self._client.build_request(method, path, json=payload)
                response = await self._client.send(request, stream=True)
                response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        if int(declared) > MAX_RESPONSE_BYTES:
                            raise PfSenseError("response_size_limit_exceeded")
                    except ValueError as exc:
                        raise PfSenseError("invalid_content_length") from exc
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise PfSenseError("response_size_limit_exceeded")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                raise PfSenseError(
                    "authentication_failed" if status == 401 else "permission_denied",
                    remediation="reauthenticate"
                    if status == 401
                    else "reconfigure_permissions",
                ) from exc
            raise PfSenseError(
                f"pfSense returned HTTP {status} for {path}",
                retryable=status in {408, 429} or status >= 500,
            ) from exc
        except httpx.RequestError as exc:
            reason = (
                "tls_validation_failed"
                if isinstance(exc, httpx.ConnectError)
                and "certificate" in str(exc).casefold()
                else "connection_failed"
            )
            raise PfSenseError(
                reason,
                retryable=reason == "connection_failed",
                remediation="reconfigure_tls"
                if reason == "tls_validation_failed"
                else "retry",
            ) from exc
        finally:
            if response is not None:
                await response.aclose()

        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PfSenseError("invalid_json_response") from exc
        if not isinstance(decoded, dict) or "data" not in decoded:
            raise PfSenseError("invalid_api_envelope")
        return decoded["data"]


_SECRET = re.compile(
    r"(?i)(authorization|password|passwd|token|api[-_ ]?key|secret)\s*[:=]\s*\S+"
)
_IPV4 = re.compile(r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])")
_IPV6 = re.compile(r"(?i)(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])")
_HOST = re.compile(
    r"(?i)\b(?=[a-z0-9.-]*[a-z])[a-z0-9-]+(?:\.[a-z0-9-]+)+\b"
)
_USERNAME = re.compile(
    r"(?i)\b(?:user(?:name)?|login|account)\s*(?:=|:|for\s+)\s*[^\s,;]+"
)
_QUERY = re.compile(r"(?i)(https?://[^\s?#]+)(?:\?[^\s#]*)?(?:#[^\s]*)?")


def redact_log_text(value: str) -> str:
    bounded = value.strip()[:4096]
    bounded = _SECRET.sub(r"\1=[redacted]", bounded)
    bounded = _USERNAME.sub("user=[redacted]", bounded)
    bounded = _QUERY.sub(r"\1?[query-redacted]", bounded)
    bounded = _IPV4.sub("[ip]", bounded)
    bounded = _IPV6.sub("[ip]", bounded)
    return _HOST.sub("[host]", bounded)[:512]


def _structured_log_record(record: dict[str, Any]) -> dict[str, Any]:
    """Reduce an untrusted appliance log row to bounded, non-identifying fields."""
    message = redact_log_text(str(record.get("text") or record.get("message") or ""))
    event_id = hashlib.sha256(message.encode()).hexdigest()[:24]
    action = str(record.get("action") or "unknown").casefold()
    severity = str(record.get("severity") or record.get("level") or "unknown").casefold()
    return {
        "event_id": event_id,
        "timestamp": str(record.get("timestamp") or record.get("time") or "")[:64],
        "action": action if action in {"allow", "block", "reject"} else "unknown",
        "severity": severity
        if severity in {"debug", "info", "notice", "warning", "error", "critical"}
        else "unknown",
        "interface_present": bool(record.get("interface") or record.get("if")),
    }
