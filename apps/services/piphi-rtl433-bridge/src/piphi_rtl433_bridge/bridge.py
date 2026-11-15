from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import AsyncExitStack
import hashlib
import json
import logging
import time
from typing import Any

import aiomqtt
import httpx

from .config import (
    BridgeConfig,
    build_model_packets_topic,
    build_packet_envelope,
    build_packets_topic,
)

logger = logging.getLogger("piphi_rtl433_bridge")


class Rtl433Bridge:
    """Run rtl_433 and forward decoded JSON packets into a PiPhi runtime."""

    def __init__(self, config: BridgeConfig):
        self.config = config
        self.forwarded_count = 0
        self.invalid_line_count = 0
        self.dropped_count = 0
        self.duplicate_count = 0
        self.retry_count = 0
        self.failed_count = 0
        self.last_forward_at: float | None = None
        self._fingerprints: OrderedDict[str, float] = OrderedDict()

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("bridge_cycle_failed error=%s", exc)
            await asyncio.sleep(self.config.retry_delay_seconds)

    async def run_once(self) -> None:
        logger.info(
            "starting_rtl433_bridge command=%s ingest_url=%s",
            " ".join(self.config.rtl433_command),
            self.config.runtime_ingest_url,
        )
        process = await asyncio.create_subprocess_exec(
            *self.config.rtl433_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_task = asyncio.create_task(self._forward_stdout(process))
            stderr_task = asyncio.create_task(self._log_stderr(process))
            await asyncio.gather(stdout_task, stderr_task)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

        logger.warning("rtl433_process_exited returncode=%s", process.returncode)

    async def _forward_stdout(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        await asyncio.sleep(self.config.startup_delay_seconds)
        async with AsyncExitStack() as stack:
            http_client: httpx.AsyncClient | None = None
            mqtt_client: aiomqtt.Client | None = None
            if self.config.http_forward_enabled:
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(timeout=self.config.forward_timeout_seconds)
                )
            if self.config.mqtt_enabled:
                mqtt_client = await stack.enter_async_context(
                    aiomqtt.Client(
                        hostname=self.config.mqtt_hostname,
                        port=self.config.mqtt_port,
                        username=self.config.mqtt_username,
                        password=self.config.mqtt_password,
                        identifier=self.config.mqtt_client_id,
                    )
                )
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=self.config.queue_size)

            async def produce() -> None:
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    packet = parse_packet_line(line, max_packet_bytes=self.config.max_packet_bytes)
                    if packet is None:
                        self.invalid_line_count += 1
                        continue
                    if self._is_duplicate(packet):
                        self.duplicate_count += 1
                        continue
                    try:
                        queue.put_nowait(packet)
                    except asyncio.QueueFull:
                        self.dropped_count += 1
                await queue.put(None)

            async def consume() -> None:
                while True:
                    packet = await queue.get()
                    try:
                        if packet is None:
                            return
                        await self.forward_packet(http_client, mqtt_client, packet)
                    finally:
                        queue.task_done()

            await asyncio.gather(produce(), consume())

    async def _log_stderr(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            message = line.decode("utf-8", errors="replace").strip()
            if message:
                logger.info("rtl433 stderr=%s", message)

    async def forward_packet(
        self,
        http_client: httpx.AsyncClient | None,
        mqtt_client: aiomqtt.Client | None,
        packet: dict[str, Any],
    ) -> None:
        for attempt in range(1, self.config.max_forward_attempts + 1):
            try:
                await self._forward_packet_http(http_client, packet)
                await self._forward_packet_mqtt(mqtt_client, packet)
                self.forwarded_count += 1
                self.last_forward_at = time.monotonic()
                logger.info(
                    "packet_forwarded count=%s model=%s id=%s",
                    self.forwarded_count,
                    packet.get("model"),
                    packet.get("id"),
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt >= self.config.max_forward_attempts:
                    self.failed_count += 1
                    self.dropped_count += 1
                    logger.error("packet_forward_exhausted attempts=%s error=%s", attempt, exc)
                    return
                self.retry_count += 1
                delay = min(self.config.retry_delay_seconds * (2 ** (attempt - 1)), 30.0)
                logger.warning("packet_forward_failed attempt=%s error=%s retrying_in=%ss", attempt, exc, delay)
                await asyncio.sleep(delay)

    def _is_duplicate(self, packet: dict[str, Any]) -> bool:
        if self.config.dedup_window_seconds <= 0:
            return False
        now = time.monotonic()
        cutoff = now - self.config.dedup_window_seconds
        while self._fingerprints:
            _, seen_at = next(iter(self._fingerprints.items()))
            if seen_at >= cutoff:
                break
            self._fingerprints.popitem(last=False)
        canonical = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        seen_at = self._fingerprints.get(fingerprint)
        self._fingerprints[fingerprint] = now
        self._fingerprints.move_to_end(fingerprint)
        return seen_at is not None and seen_at >= cutoff

    async def _forward_packet_http(
        self,
        client: httpx.AsyncClient | None,
        packet: dict[str, Any],
    ) -> None:
        if not self.config.http_forward_enabled:
            return
        if client is None:
            raise RuntimeError("HTTP forwarding is enabled but no HTTP client is available")
        response = await client.post(
            self.config.runtime_ingest_url,
            json=packet,
            headers=self.config.extra_headers,
        )
        response.raise_for_status()

    async def _forward_packet_mqtt(
        self,
        client: aiomqtt.Client | None,
        packet: dict[str, Any],
    ) -> None:
        if not self.config.mqtt_enabled:
            return
        if client is None:
            raise RuntimeError("MQTT publishing is enabled but no MQTT client is available")

        envelope = build_packet_envelope(packet)
        packets_topic = build_packets_topic(self.config.mqtt_topic_root)
        await client.publish(
            packets_topic,
            payload=json.dumps(envelope),
            qos=self.config.mqtt_qos,
        )

        model = packet.get("model")
        if model:
            await client.publish(
                build_model_packets_topic(self.config.mqtt_topic_root, str(model)),
                payload=json.dumps(envelope),
                qos=self.config.mqtt_qos,
            )


def parse_packet_line(line: bytes | str, *, max_packet_bytes: int = 65_536) -> dict[str, Any] | None:
    if len(line) > max_packet_bytes:
        return None
    if isinstance(line, bytes):
        text = line.decode("utf-8", errors="replace").strip()
    else:
        text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if not _bounded_json(payload):
        return None
    return payload


def _bounded_json(value: Any, *, depth: int = 0) -> bool:
    if depth > 5:
        return False
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= 2048
    if isinstance(value, list):
        return len(value) <= 128 and all(_bounded_json(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        return len(value) <= 256 and all(
            isinstance(key, str)
            and len(key) <= 128
            and _bounded_json(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False
