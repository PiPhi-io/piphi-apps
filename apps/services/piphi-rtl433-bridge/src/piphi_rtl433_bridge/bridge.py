from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
import logging
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
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                packet = parse_packet_line(line)
                if packet is None:
                    self.invalid_line_count += 1
                    continue
                await self.forward_packet(http_client, mqtt_client, packet)

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
        while True:
            try:
                await self._forward_packet_http(http_client, packet)
                await self._forward_packet_mqtt(mqtt_client, packet)
                self.forwarded_count += 1
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
                logger.warning("packet_forward_failed error=%s retrying_in=%ss", exc, self.config.retry_delay_seconds)
                await asyncio.sleep(self.config.retry_delay_seconds)

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


def parse_packet_line(line: bytes | str) -> dict[str, Any] | None:
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
    return payload
