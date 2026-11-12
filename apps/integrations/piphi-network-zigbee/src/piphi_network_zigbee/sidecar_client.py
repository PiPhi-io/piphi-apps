from __future__ import annotations

from typing import Any

import httpx

from .settings import DEFAULT_MQTT_BASE_TOPIC, DEFAULT_SIDECAR_BASE_URL
from .zigbee_devices import normalize_zigbee2mqtt_device


class SidecarUnavailable(RuntimeError):
    pass


class Zigbee2MqttSidecarClient:
    def __init__(self, base_url: str | None = None, timeout_seconds: float = 5.0) -> None:
        self.base_url = (base_url or DEFAULT_SIDECAR_BASE_URL).strip().rstrip("/")
        self.timeout_seconds = timeout_seconds

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
            if isinstance(device, dict)
        ]

    async def _safe_snapshot(self) -> dict[str, Any]:
        try:
            return await self.snapshot()
        except SidecarUnavailable:
            return {}

    async def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise SidecarUnavailable(f"Unable to reach Zigbee2MQTT sidecar at {url}") from exc
