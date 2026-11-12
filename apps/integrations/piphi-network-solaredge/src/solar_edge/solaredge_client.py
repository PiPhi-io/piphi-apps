from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .schemas import DeviceConfig


class SolarEdgeClientError(RuntimeError):
    """Base error exposed by the SolarEdge adapter."""


class SolarEdgeAuthenticationError(SolarEdgeClientError):
    pass


class SolarEdgeRateLimitError(SolarEdgeClientError):
    pass


class SolarEdgeRequestError(SolarEdgeClientError):
    """A definite caller error that will not succeed unchanged."""


class SolarEdgeTransientError(SolarEdgeClientError):
    """A network or upstream failure that Core may safely retry."""


@dataclass(frozen=True, slots=True)
class SolarEdgeReading:
    site_id: int
    site_name: str
    site_status: str
    last_update: str | None
    unit: str
    production_power_w: float | None
    consumption_power_w: float | None
    grid_power_w: float | None
    battery_power_w: float | None
    battery_soc_percent: float | None
    today_energy_kwh: float | None = None
    month_energy_kwh: float | None = None
    year_energy_kwh: float | None = None
    lifetime_energy_kwh: float | None = None
    lifetime_revenue: float | None = None


class SolarEdgeClient(Protocol):
    async def authenticate(self, config: DeviceConfig) -> None: ...
    async def read(self, *, include_summary: bool) -> SolarEdgeReading: ...
    async def close(self) -> None: ...


class MonitoringApiClient:
    """Testable adapter around the V1-only ``solaredge`` package."""

    def __init__(self) -> None:
        self._client = None
        self._site_id = 0
        self._site_name = "SolarEdge site"
        self._site_status = "Unknown"
        self._summary: dict[str, Any] = {}

    async def authenticate(self, config: DeviceConfig) -> None:
        import httpx
        from solaredge import AsyncMonitoringClient

        self._site_id = config.site_id
        self._client = AsyncMonitoringClient(config.secret_api_key())
        try:
            payload = await self._client.get_site_details(config.site_id)
        except httpx.HTTPStatusError as exc:
            await self.close()
            status = exc.response.status_code
            if status in {401, 403}:
                raise SolarEdgeAuthenticationError("SolarEdge rejected the API key or site access.") from exc
            if status == 404:
                raise SolarEdgeAuthenticationError("SolarEdge did not find that Site ID.") from exc
            if status == 429:
                raise SolarEdgeRateLimitError("SolarEdge API request quota is exhausted.") from exc
            error_type = SolarEdgeTransientError if status >= 500 else SolarEdgeRequestError
            raise error_type(f"SolarEdge API returned HTTP {status}.") from exc
        details = payload.get("details", {})
        self._site_name = str(details.get("name") or config.alias or f"SolarEdge site {config.site_id}")
        self._site_status = str(details.get("status") or "Unknown")

    async def read(self, *, include_summary: bool) -> SolarEdgeReading:
        if self._client is None:
            raise SolarEdgeClientError("SolarEdge client is not authenticated")
        try:
            flow_payload = await self._client.get_current_power_flow(self._site_id)
            if include_summary:
                self._summary = await self._client.get_overview([self._site_id])
        except Exception as exc:
            raise _translate_error(exc) from exc

        flow = flow_payload.get("siteCurrentPowerFlow", {})
        factor = _power_factor(flow.get("unit"))
        connections = flow.get("connections") if isinstance(flow.get("connections"), list) else []
        overview = self._summary.get("overview", {})
        return SolarEdgeReading(
            site_id=self._site_id,
            site_name=self._site_name,
            site_status=self._site_status,
            last_update=_optional_text(overview.get("lastUpdateTime")),
            unit=str(flow.get("unit") or "W"),
            production_power_w=_node_power(flow, "PV", factor),
            consumption_power_w=_node_power(flow, "LOAD", factor),
            grid_power_w=_signed_node_power(flow, "GRID", connections, factor),
            battery_power_w=_signed_node_power(flow, "STORAGE", connections, factor),
            battery_soc_percent=_node_number(flow, "STORAGE", "chargeLevel"),
            today_energy_kwh=_energy_kwh(overview.get("lastDayData")),
            month_energy_kwh=_energy_kwh(overview.get("lastMonthData")),
            year_energy_kwh=_energy_kwh(overview.get("lastYearData")),
            lifetime_energy_kwh=_energy_kwh(overview.get("lifeTimeData")),
            lifetime_revenue=_nested_number(overview.get("lifeTimeData"), "revenue"),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None


def _translate_error(exc: Exception) -> SolarEdgeClientError:
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status == 429:
                return SolarEdgeRateLimitError("SolarEdge API request quota is exhausted.")
            if status in {401, 403}:
                return SolarEdgeAuthenticationError("SolarEdge rejected the API key or site access.")
            error_type = SolarEdgeTransientError if status >= 500 else SolarEdgeRequestError
            return error_type(f"SolarEdge API returned HTTP {status}.")
        if isinstance(exc, httpx.HTTPError):
            return SolarEdgeTransientError(f"Could not reach SolarEdge: {exc}")
    except ImportError:
        pass
    return exc if isinstance(exc, SolarEdgeClientError) else SolarEdgeClientError(str(exc))


def _power_factor(unit: object) -> float:
    return {"W": 1.0, "KW": 1000.0, "MW": 1_000_000.0}.get(str(unit or "W").upper(), 1.0)


def _node_power(flow: dict[str, Any], node: str, factor: float) -> float | None:
    return _node_number(flow, node, "currentPower", factor=factor)


def _node_number(flow: dict[str, Any], node: str, key: str, *, factor: float = 1.0) -> float | None:
    value = flow.get(node)
    if not isinstance(value, dict) or value.get(key) is None:
        return None
    return float(value[key]) * factor


def _signed_node_power(flow: dict[str, Any], node: str, connections: list[Any], factor: float) -> float | None:
    power = _node_power(flow, node, factor)
    if power is None:
        return None
    normalized = [{"from": str(item.get("from", "")).upper(), "to": str(item.get("to", "")).upper()} for item in connections if isinstance(item, dict)]
    if any(item["from"] == node for item in normalized):
        return power
    if any(item["to"] == node for item in normalized):
        return -power
    return power


def _energy_kwh(value: object) -> float | None:
    amount = _nested_number(value, "energy")
    return amount / 1000.0 if amount is not None else None


def _nested_number(value: object, key: str) -> float | None:
    return float(value[key]) if isinstance(value, dict) and value.get(key) is not None else None


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None
