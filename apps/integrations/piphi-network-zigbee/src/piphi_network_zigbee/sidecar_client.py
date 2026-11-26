from __future__ import annotations

import asyncio
import os
import ssl
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
        self._ssl_context = _sidecar_ssl_context(self.base_url)

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
        return payload if isinstance(payload, dict) else {
            "messages": [],
            "sequence": after_sequence,
            "gap": None,
        }

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

    async def mqtt_publish_confirmed(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        dry_run: bool = False,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        state_topic = topic.removesuffix("/set")
        before = await self.mqtt_messages([state_topic]) if not dry_run else {"sequence": 0}
        cursor = int(before.get("sequence") or 0)
        published = await self.mqtt_publish(topic, payload, dry_run=dry_run)
        if dry_run:
            return {**published, "outcome": "planned"}
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            replay = await self.mqtt_messages([state_topic], after_sequence=cursor)
            cursor = max(cursor, int(replay.get("sequence") or 0))
            for message in replay.get("messages") or []:
                observed = message.get("payload") if isinstance(message, dict) else None
                if isinstance(observed, dict) and all(observed.get(key) == value for key, value in payload.items()):
                    return {
                        **published,
                        "status": "confirmed",
                        "outcome": "device_state_converged",
                        "observed": {key: observed.get(key) for key in payload},
                    }
            await asyncio.sleep(0.05)
        raise SidecarUnavailable(
            "Zigbee2MQTT accepted the publish but device state did not converge before timeout"
        )

    async def _safe_snapshot(self) -> dict[str, Any]:
        try:
            return await self.snapshot()
        except SidecarUnavailable:
            return {}

    async def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, verify=self._ssl_context) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise SidecarUnavailable(f"Unable to reach Zigbee2MQTT sidecar at {url}") from exc

    async def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, verify=self._ssl_context) as client:
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
        on_gap: Callable[[dict[str, int]], None] | None = None,
        token: str | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.client = Zigbee2MqttSidecarClient(base_url=base_url, token=token)
        self.topics = list(dict.fromkeys(topics))
        self.on_message = on_message
        self.on_gap = on_gap
        self.poll_interval_seconds = poll_interval_seconds
        self.status = "stopped"
        self.message: str | None = None
        self.started_at: datetime | None = None
        self._after_sequence = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._gap: dict[str, int] | None = None
        self._consecutive_failures = 0

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
            "gap": self._gap,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                gap_detected = self._poll_once()
                self._consecutive_failures = 0
                self.status = "degraded" if gap_detected else "running"
                self.message = "mqtt_journal_gap" if gap_detected else None
            except SidecarUnavailable as exc:
                self._consecutive_failures += 1
                self.status = "error"
                self.message = str(exc)
            delay = min(
                30.0,
                self.poll_interval_seconds * (2 ** min(self._consecutive_failures, 5)),
            )
            self._stop.wait(delay)

    def _poll_once(self) -> bool:
        url = f"{self.client.base_url}/v1/mqtt/messages"
        headers = (
            {"Authorization": f"Bearer {self.client.token}"}
            if self.client.token
            else {}
        )
        try:
            with httpx.Client(timeout=self.client.timeout_seconds, verify=self.client._ssl_context) as client:
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
        gap = payload.get("gap") if isinstance(payload, dict) else None
        if gap is not None and not (
            isinstance(gap, dict)
            and isinstance(gap.get("from_sequence"), int)
            and isinstance(gap.get("to_sequence"), int)
        ):
            raise SidecarUnavailable("Zigbee2MQTT sidecar returned an invalid journal gap")
        self._gap = dict(gap) if gap else None
        if self._gap and self.on_gap:
            self.on_gap(dict(self._gap))
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
        return self._gap is not None


def _sidecar_ssl_context(base_url: str) -> ssl.SSLContext | bool:
    if not base_url.lower().startswith("https://"):
        return True
    ca_file = str(
        os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_CA_FILE")
        or os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_CA")
        or ""
    ).strip() or None
    cert_file = str(
        os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_CERT_FILE")
        or os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_CERT")
        or ""
    ).strip() or None
    key_file = str(
        os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_KEY_FILE")
        or os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_KEY")
        or ""
    ).strip() or None
    if bool(cert_file) != bool(key_file):
        raise ValueError("Sidecar client certificate and key must be configured together.")
    context = ssl.create_default_context(cafile=ca_file)
    if cert_file and key_file:
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context
