from __future__ import annotations

import os
from typing import Any

import httpx

from .settings import DEFAULT_MQTT_BASE_TOPIC, DEFAULT_SIDECAR_BASE_URL
from .zigbee_devices import is_import_eligible, normalize_zigbee2mqtt_device


class SidecarUnavailable(RuntimeError):
    pass


class Zigbee2MqttSidecarClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 5.0,
        token: str | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_SIDECAR_BASE_URL).strip().rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.token = str(
            token
            if token is not None
            else os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_TOKEN")
            or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")
            or ""
        ).strip()

    async def snapshot(self) -> dict[str, Any]:
        return await self._get_json("/v1/snapshot")

    async def devices(self) -> list[dict[str, Any]]:
        payload = await self._get_json("/v1/devices")
        raw_devices = payload.get("devices") if isinstance(payload, dict) else payload
        if not isinstance(raw_devices, list):
            return []
        snapshot = await self._safe_snapshot()
        base_topic = str(snapshot.get("mqtt_base_topic") or DEFAULT_MQTT_BASE_TOPIC)
        return [
            normalize_zigbee2mqtt_device(
                device,
                default_base_topic=base_topic,
                sidecar_base_url=self.base_url,
            )
            for device in raw_devices
            if isinstance(device, dict) and is_import_eligible(device)
        ]

    async def _safe_snapshot(self) -> dict[str, Any]:
        try:
            return await self.snapshot()
        except SidecarUnavailable:
            return {}

    async def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise SidecarUnavailable(f"Unable to reach Zigbee2MQTT sidecar at {url}") from exc
