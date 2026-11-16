from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
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

    async def mqtt_messages(
        self,
        topics: list[str],
        *,
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        payload = await self._post_json(
            "/v1/mqtt/messages",
            {"topics": topics, "after_sequence": after_sequence},
        )
        return payload if isinstance(payload, dict) else {"messages": [], "sequence": after_sequence}

    async def mqtt_publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if dry_run:
            return {
                "ok": True,
                "status": "planned",
                "topic": topic,
                "payload": payload,
            }
        result = await self._post_json(
            "/v1/mqtt/publish",
            {"topic": topic, "payload": payload, "dry_run": dry_run},
        )
        if not isinstance(result, dict):
            raise SidecarUnavailable("Zigbee2MQTT sidecar returned an invalid publish response")
        return result

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

    async def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise SidecarUnavailable(f"Unable to reach Zigbee2MQTT sidecar at {url}") from exc


class SidecarMessageSubscriber:
    def __init__(
        self,
        *,
        base_url: str,
        topics: list[str],
        on_message: Callable[[str, Any], None],
        token: str | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.client = Zigbee2MqttSidecarClient(base_url=base_url, token=token)
        self.topics = list(dict.fromkeys(topics))
        self.on_message = on_message
        self.poll_interval_seconds = poll_interval_seconds
        self.status = "stopped"
        self.message: str | None = None
        self.started_at: datetime | None = None
        self._after_sequence = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.topics:
            self.message = "no subscriptions"
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.status = "starting"
        self.started_at = datetime.now(UTC)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self.status = "stopped"

    def snapshot(self) -> dict[str, Any]:
        return {
            "sidecar_url": self.client.base_url,
            "status": self.status,
            "message": self.message,
            "topics": self.topics,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "sequence": self._after_sequence,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
                self.status = "running"
                self.message = None
            except SidecarUnavailable as exc:
                self.status = "error"
                self.message = str(exc)
            self._stop.wait(self.poll_interval_seconds)

    def _poll_once(self) -> None:
        url = f"{self.client.base_url}/v1/mqtt/messages"
        headers = (
            {"Authorization": f"Bearer {self.client.token}"}
            if self.client.token
            else {}
        )
        try:
            with httpx.Client(timeout=self.client.timeout_seconds) as client:
                response = client.post(
                    url,
                    headers=headers,
                    json={
                        "topics": self.topics,
                        "after_sequence": self._after_sequence,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise SidecarUnavailable(
                f"Unable to reach Zigbee2MQTT sidecar at {url}"
            ) from exc
        messages = payload.get("messages") if isinstance(payload, dict) else []
        if not isinstance(messages, list):
            raise SidecarUnavailable("Zigbee2MQTT sidecar returned invalid MQTT messages")
        for message in messages:
            if not isinstance(message, dict):
                continue
            topic = str(message.get("topic") or "")
            if topic not in self.topics:
                continue
            sequence = message.get("sequence")
            if isinstance(sequence, int):
                self._after_sequence = max(self._after_sequence, sequence)
            self.on_message(topic, message.get("payload"))
        sequence = payload.get("sequence") if isinstance(payload, dict) else None
        if isinstance(sequence, int):
            self._after_sequence = max(self._after_sequence, sequence)
