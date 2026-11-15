from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from datetime import UTC, datetime
from time import monotonic_ns

from .ble_models import SCHEMA_VERSION, Advertisement, Matcher, ScanMode, bounded_hex_map, utc_now
from .scanner import BleakCallbackScanner, CapabilityAdapter, Scanner
from .bluez import default_capability_adapter

DEFAULT_CAPACITY = 128
MAX_CAPACITY = 1024
MAX_REPLAY_LIMIT = 500
MAX_CHECKPOINT_ITEMS = 256
CHECKPOINT_MAX_AGE_MS = 300_000
DEDUP_WINDOW_MS = 1_000


@dataclass(slots=True)
class Consumer:
    consumer_id: str
    token_digest: str
    matcher: Matcher
    mode: ScanMode
    capacity: int
    queue: deque[dict] = field(default_factory=deque)
    latest: dict[str, dict] = field(default_factory=dict)
    high_water: int = 0
    dropped: int = 0
    coalesced: int = 0
    lost_through: int = 0


class Gateway:
    def __init__(
        self,
        scanner: Scanner | None = None,
        capability_adapter: CapabilityAdapter | None = None,
        *,
        receiver_id: str | None = None,
        secret_path: str | Path | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        self.scanner = scanner or BleakCallbackScanner(os.getenv("PIPHI_BLE_ADAPTER"))
        self.capability_adapter = capability_adapter or default_capability_adapter(self.scanner.adapter)
        self.receiver_id = receiver_id or os.getenv("PIPHI_BLE_RECEIVER_ID", "local-receiver")
        self.secret_path = Path(secret_path or os.getenv("PIPHI_BLE_HANDLE_KEY_PATH", "./data/ble-handle.key"))
        self.checkpoint_path = Path(checkpoint_path or os.getenv("PIPHI_BLE_CHECKPOINT_PATH", "./data/ble-latest.json"))
        self.consumers: dict[str, Consumer] = {}
        self.scanner_state = "stopped"
        self.service_available = False
        self.receiver_healthy = False
        self.scan_mode: ScanMode | None = None
        self.sequence = 0
        self.reconnects = 0
        self.observations_received = 0
        self.observations_deduplicated = 0
        self._last_observation_ms: int | None = None
        self._secret: bytes | None = None
        self._dedup: dict[str, tuple[int, bytes]] = {}
        self._checkpoint: list[dict] = []
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._load_secret()
        self._load_checkpoint()
        self.service_available = True
        await self._apply_plan()

    async def stop(self) -> None:
        async with self._lock:
            if self.scanner_state in {"scanning", "starting", "failed"}:
                await self._safe_stop()
            self.scanner_state = "stopped"
            self.receiver_healthy = False
            self.service_available = False
            self._save_checkpoint()

    def authorize(self, consumer_id: str, token: str) -> Consumer:
        consumer = self.consumers.get(consumer_id)
        if consumer is None or not hmac.compare_digest(consumer.token_digest, self._token_digest(token)):
            raise PermissionError("consumer authorization failed")
        return consumer

    async def register(
        self, consumer_id: str, token: str, matcher: Matcher, mode: ScanMode, capacity: int
    ) -> Consumer:
        if not matcher.bounded:
            raise ValueError("at least one bounded matcher scope is required")
        if not 1 <= capacity <= MAX_CAPACITY:
            raise ValueError(f"queue_capacity must be between 1 and {MAX_CAPACITY}")
        existing = self.consumers.get(consumer_id)
        if existing and not hmac.compare_digest(existing.token_digest, self._token_digest(token)):
            raise PermissionError("consumer authorization failed")
        consumer = Consumer(consumer_id, self._token_digest(token), matcher, mode, capacity)
        if existing:
            consumer.queue = deque(list(existing.queue)[-capacity:])
            consumer.latest = existing.latest
            consumer.high_water = min(existing.high_water, capacity)
            consumer.dropped = existing.dropped
            consumer.coalesced = existing.coalesced
            consumer.lost_through = existing.lost_through
        self.consumers[consumer_id] = consumer
        self._replay_checkpoint(consumer)
        await self._apply_plan()
        return consumer

    async def unregister(self, consumer_id: str, token: str) -> None:
        self.authorize(consumer_id, token)
        del self.consumers[consumer_id]
        await self._apply_plan()

    def plan(self) -> ScanMode | None:
        modes = {consumer.mode for consumer in self.consumers.values()}
        if "active" in modes:
            return "active"
        if "auto" in modes:
            return "auto"
        if "passive" in modes:
            return "passive"
        return None

    async def _apply_plan(self) -> None:
        desired = self.plan()
        async with self._lock:
            if desired == self.scan_mode and self.scanner_state == ("scanning" if desired else "stopped"):
                return
            if self.scanner_state in {"scanning", "starting", "failed"}:
                await self._safe_stop()
            self.scan_mode = desired
            if desired is None:
                self.scanner_state = "stopped"
                self.receiver_healthy = False
                return
            self.scanner_state = "starting"
            try:
                await self.scanner.start(desired, self.ingest)
            except Exception:
                self.scanner_state = "failed"
                self.receiver_healthy = False
                return
            self.scanner_state = "scanning"
            self.receiver_healthy = True

    async def restart(self) -> None:
        self.reconnects += 1
        async with self._lock:
            await self._safe_stop()
            self.scan_mode = None
        await self._apply_plan()

    async def supervise_once(self) -> bool:
        """Recover only a supported platform adapter whose scan has degraded."""
        if not self.service_available or not self.consumers:
            return False
        diagnostics = await self.capability_adapter.diagnostics()
        platform_degraded = diagnostics.get("supported") is True and (
            diagnostics.get("available") is not True
            or diagnostics.get("adapter_powered") is False
            or (self.scanner_state == "scanning" and diagnostics.get("adapter_discovering") is False)
        )
        if self.scanner_state != "failed" and not platform_degraded:
            return False
        if not await self.capability_adapter.recover():
            return False
        await self.restart()
        return self.scanner_state == "scanning"

    async def supervise(self, interval_seconds: float = 5.0) -> None:
        while self.service_available:
            await self.supervise_once()
            await asyncio.sleep(interval_seconds)

    async def _safe_stop(self) -> None:
        try:
            await self.scanner.stop()
        finally:
            self.scanner_state = "stopped"
            self.receiver_healthy = False

    async def ingest(self, advert: Advertisement) -> None:
        self.observations_received += 1
        now_ms = monotonic_ns() // 1_000_000
        if advert.observed_monotonic_ms > now_ms + 5_000:
            return
        handle = self._handle(advert.address)
        payload_fingerprint = repr((advert.rssi, advert.tx_power, advert.connectable, advert.address_type,
            sorted(advert.service_uuids), sorted(advert.manufacturer_data.items()), sorted(advert.service_data.items()))).encode()
        previous = self._dedup.get(handle)
        if previous and advert.observed_monotonic_ms <= previous[0]:
            self.observations_deduplicated += 1
            return
        if previous and advert.observed_monotonic_ms - previous[0] <= DEDUP_WINDOW_MS and previous[1] == payload_fingerprint:
            self.observations_deduplicated += 1
            return
        self._dedup[handle] = (advert.observed_monotonic_ms, payload_fingerprint)
        self.sequence += 1
        observation = {
            "schema_version": SCHEMA_VERSION,
            "sequence": self.sequence,
            "device_handle": handle,
            "receiver_id": self.receiver_id,
            "receiver_kind": self.scanner.receiver_kind,
            "observed_monotonic_ms": advert.observed_monotonic_ms,
            "ingested_at": utc_now(),
            "replayed": False,
            "rssi": max(-127, min(20, int(advert.rssi))),
            "connectable": advert.connectable,
            "address_type": advert.address_type if advert.address_type in {"public", "random", "public_identity", "random_identity"} else "unknown",
            "service_uuids": sorted(set(uuid.lower()[:64] for uuid in advert.service_uuids))[:64],
            "manufacturer_data": bounded_hex_map(advert.manufacturer_data, numeric_keys=True),
            "service_data": bounded_hex_map(advert.service_data),
        }
        if advert.tx_power is not None:
            observation["tx_power"] = max(-127, min(127, int(advert.tx_power)))
        self._last_observation_ms = now_ms
        for consumer in self.consumers.values():
            if consumer.matcher.matches(handle, advert):
                self._enqueue(consumer, observation)
        self._checkpoint = self._merge_checkpoint(observation)
        self._save_checkpoint()

    def _enqueue(self, consumer: Consumer, observation: dict) -> None:
        item = dict(observation)
        consumer.latest[item["device_handle"]] = item
        if len(consumer.queue) >= consumer.capacity:
            replacement = next((index for index, old in enumerate(consumer.queue)
                                if old["device_handle"] == item["device_handle"]), None)
            if replacement is not None:
                consumer.lost_through = max(consumer.lost_through, consumer.queue[replacement]["sequence"])
                del consumer.queue[replacement]
                consumer.coalesced += 1
            else:
                dropped = consumer.queue.popleft()
                consumer.lost_through = max(consumer.lost_through, dropped["sequence"])
                consumer.dropped += 1
        consumer.queue.append(item)
        consumer.high_water = max(consumer.high_water, len(consumer.queue))

    def observations(self, consumer: Consumer, after: int, limit: int) -> list[dict]:
        return [item for item in consumer.queue if item["sequence"] > after][:limit]

    def snapshot(self, consumer: Consumer) -> list[dict]:
        return sorted(consumer.latest.values(), key=lambda item: item["sequence"])

    def cursor_gap(self, consumer: Consumer, after: int) -> bool:
        return after < consumer.lost_through

    def _handle(self, address: str) -> str:
        if self._secret is None:
            self._load_secret()
        digest = hmac.new(self._secret or b"", address.strip().lower().encode(), hashlib.sha256).hexdigest()
        return f"ble_{digest[:32]}"

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _load_secret(self) -> None:
        self.secret_path.parent.mkdir(parents=True, exist_ok=True)
        if self.secret_path.exists():
            self._secret = self.secret_path.read_bytes()
        else:
            self._secret = os.urandom(32)
            self.secret_path.write_bytes(self._secret)
            try:
                self.secret_path.chmod(0o600)
            except OSError:
                pass

    def _merge_checkpoint(self, observation: dict) -> list[dict]:
        by_handle = {item["device_handle"]: item for item in self._checkpoint}
        by_handle[observation["device_handle"]] = observation
        return sorted(by_handle.values(), key=lambda item: item["sequence"])[-MAX_CHECKPOINT_ITEMS:]

    def _load_checkpoint(self) -> None:
        try:
            payload = json.loads(self.checkpoint_path.read_text())
            age_ms = max(0, int(__import__("time").time() * 1000) - int(payload["saved_at_ms"]))
            if age_ms <= CHECKPOINT_MAX_AGE_MS and isinstance(payload.get("observations"), list):
                now = datetime.now(UTC)
                self._checkpoint = [item for item in payload["observations"][-MAX_CHECKPOINT_ITEMS:]
                                    if self._checkpoint_item_age_ms(item, now) <= CHECKPOINT_MAX_AGE_MS]
                self.sequence = max((int(item.get("sequence", 0)) for item in self._checkpoint), default=0)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self._checkpoint = []

    @staticmethod
    def _checkpoint_item_age_ms(item: dict, now: datetime) -> int:
        try:
            ingested = datetime.fromisoformat(str(item["ingested_at"]).replace("Z", "+00:00"))
            return max(0, int((now - ingested).total_seconds() * 1000))
        except (KeyError, TypeError, ValueError):
            return CHECKPOINT_MAX_AGE_MS + 1

    def _save_checkpoint(self) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"saved_at_ms": int(__import__("time").time() * 1000), "observations": self._checkpoint[-MAX_CHECKPOINT_ITEMS:]}
        temporary = self.checkpoint_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")))
        temporary.replace(self.checkpoint_path)

    def _replay_checkpoint(self, consumer: Consumer) -> None:
        for item in self._checkpoint:
            handle = str(item.get("device_handle", ""))
            if consumer.matcher.matches(handle, None, item):
                replay = dict(item)
                replay["replayed"] = True
                self._enqueue(consumer, replay)

    async def diagnostics(self) -> dict:
        now_ms = monotonic_ns() // 1_000_000
        capability = await self.capability_adapter.diagnostics()
        return {
            "service_available": self.service_available,
            "scanner_state": self.scanner_state,
            "scan_mode": self.scan_mode,
            "adapter": self.scanner.adapter,
            "backend": self.scanner.backend,
            "receiver_id": self.receiver_id,
            "receiver_kind": self.scanner.receiver_kind,
            "receiver_healthy": self.receiver_healthy,
            "last_observation_age_ms": None if self._last_observation_ms is None else max(0, now_ms - self._last_observation_ms),
            "reconnects": self.reconnects,
            "observations_received": self.observations_received,
            "observations_deduplicated": self.observations_deduplicated,
            "consumers": {
                key: {"queue_depth": len(value.queue), "queue_capacity": value.capacity,
                      "queue_high_water": value.high_water, "drops": value.dropped,
                      "coalesces": value.coalesced}
                for key, value in sorted(self.consumers.items())
            },
            "platform_capabilities": capability,
        }


gateway = Gateway()
