from __future__ import annotations

import os
from typing import Any

import httpx


class SidecarError(RuntimeError):
    pass


class ModbusSidecarClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = str(
            base_url or os.getenv("PIPHI_MODBUS_SIDECAR_URL") or "http://piphi-modbus-rtu-sidecar:4212"
        ).rstrip("/")
        self.token = str(
            token
            if token is not None
            else os.getenv("PIPHI_MODBUS_SIDECAR_TOKEN")
            or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")
            or ""
        ).strip()
        self.timeout_seconds = timeout_seconds

    async def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/config", json=payload)

    async def snapshot(self, config_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET", "/v1/modbus/snapshot", params={"config_id": config_id}
        )
        if not isinstance(payload, dict) or payload.get("schema_version") != "piphi.modbus.snapshot.v1":
            raise SidecarError("sidecar returned an unsupported snapshot contract")
        return payload

    async def events(self, config_id: str, *, after: int, limit: int = 500) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            "/v1/modbus/events",
            params={"config_id": config_id, "after": after, "limit": limit},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise SidecarError("sidecar returned an invalid event replay contract")
        return payload

    async def refresh(self, config_id: str, point_id: str | None = None) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/modbus/refresh",
            json={"config_id": config_id, **({"point_id": point_id} if point_id else {})},
        )

    async def write(self, config_id: str, point_id: str, value: Any) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/modbus/write",
            json={"config_id": config_id, "point_id": point_id, "value": value},
        )

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
            raise SidecarError(f"Modbus sidecar request failed: {method} {path}") from exc
