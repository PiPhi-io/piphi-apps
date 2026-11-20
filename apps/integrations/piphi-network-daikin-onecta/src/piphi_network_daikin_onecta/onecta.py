from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

API_ORIGIN = "https://api.onecta.daikineurope.com"


class OnectaError(RuntimeError):
    def __init__(
        self, category: str, *, retry_after_seconds: int | None = None
    ) -> None:
        super().__init__(category)
        self.category = category
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class Quota:
    minute_remaining: int | None = None
    day_remaining: int | None = None
    reset_at: str | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    devices: tuple[dict[str, Any], ...]
    quota: Quota


def _integer(headers: httpx.Headers, *names: str) -> int | None:
    for name in names:
        value = headers.get(name)
        if value is not None:
            try:
                return max(0, int(value))
            except ValueError:
                return None
    return None


def _retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(86400, max(0, int(value)))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return min(86400, max(0, int((parsed - datetime.now(UTC)).total_seconds())))
        except (TypeError, ValueError):
            return None


def quota_from_headers(headers: httpx.Headers) -> Quota:
    return Quota(
        minute_remaining=_integer(
            headers, "X-RateLimit-Remaining-Minute", "X-RateLimit-Remaining"
        ),
        day_remaining=_integer(headers, "X-RateLimit-Remaining-Day"),
        reset_at=headers.get("X-RateLimit-Reset"),
        retry_after_seconds=_retry_after(headers),
    )


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    category = (
        "invalid_auth"
        if status == 401
        else "permission_denied"
        if status == 403
        else "rate_limited"
        if status == 429
        else "provider_unavailable"
        if status >= 500
        else "provider_request_rejected"
    )
    raise OnectaError(category, retry_after_seconds=_retry_after(response.headers))


class OnectaClient:
    def __init__(
        self,
        access_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 20,
        base_url: str = API_ORIGIN,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_devices(self) -> AccountSnapshot:
        try:
            response = await self._client.get("/v1/gateway-devices")
        except httpx.TimeoutException as exc:
            raise OnectaError("timeout") from exc
        except httpx.HTTPError as exc:
            raise OnectaError("provider_unavailable") from exc
        _raise_for_status(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise OnectaError("malformed_response") from exc
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise OnectaError("malformed_response")
        return AccountSnapshot(tuple(payload), quota_from_headers(response.headers))

    async def set_target_temperature(
        self,
        *,
        gateway_id: str,
        management_point_id: str,
        path: str,
        value: float,
    ) -> Quota:
        gateway_segment = quote(gateway_id, safe="")
        point_segment = quote(management_point_id, safe="")
        try:
            response = await self._client.patch(
                f"/v1/gateway-devices/{gateway_segment}/management-points/"
                f"{point_segment}/characteristics/temperatureControl",
                json={"path": path, "value": value},
            )
        except httpx.TimeoutException as exc:
            raise OnectaError("timeout") from exc
        except httpx.HTTPError as exc:
            raise OnectaError("provider_unavailable") from exc
        _raise_for_status(response)
        return quota_from_headers(response.headers)
