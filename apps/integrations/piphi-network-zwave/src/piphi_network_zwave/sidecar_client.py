from __future__ import annotations

import os
from typing import Any

import httpx

from .settings import DEFAULT_SIDECAR_BASE_URL


class SidecarError(RuntimeError):
    pass


class ZWaveSidecarClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or DEFAULT_SIDECAR_BASE_URL).strip().rstrip("/")
        self.token = str(
            token
            if token is not None
            else os.getenv("PIPHI_ZWAVE_SIDECAR_TOKEN")
            or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")
            or ""
        ).strip()
        self.timeout_seconds = timeout_seconds

    async def snapshot(self) -> dict[str, Any]:
        payload = await self._request("GET", "/v1/zwave/snapshot")
        if not isinstance(payload, dict) or payload.get("schema_version") != "piphi.zwave.snapshot.v1":
            raise SidecarError("sidecar returned an unsupported snapshot contract")
        return payload

    async def events(self, *, after: int, limit: int = 500) -> dict[str, Any]:
        payload = await self._request(
            "GET", "/v1/zwave/events", params={"after": after, "limit": limit}
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise SidecarError("sidecar returned an invalid event replay contract")
        return payload

    async def command(
        self,
        *,
        config_id: str,
        command: str,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {}
        if idempotency_key:
            headers["X-PiPhi-Idempotency-Key"] = idempotency_key
        payload = await self._request(
            "POST",
            "/command",
            json={
                "command": command,
                "config_id": config_id,
                "device_id": "zwave-js-service",
                "params": params or {},
            },
            headers=headers,
        )
        if not isinstance(payload, dict):
            raise SidecarError("sidecar returned an invalid command response")
        return payload

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=headers, **kwargs
                )
                response.raise_for_status()
                return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise SidecarError(f"Z-Wave sidecar request failed: {method} {path}") from exc
