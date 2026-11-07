from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from piphi_network_thinqconnect.lib.refrigerator import REFRIGERATOR_DEVICE_TYPES

MAX_MESSAGE_BYTES = 1_048_576
DEFAULT_RENEWAL_SECONDS = 24 * 60 * 60
DEFAULT_DEDUP_TTL_SECONDS = 10 * 60
DEVICE_STATUS_MESSAGE = "DEVICE_STATUS"
DEVICE_PUSH_MESSAGE = "DEVICE_PUSH"
REFRIGERATOR_PUSH_EVENTS = frozenset(
    {
        "refrigerator.door.opened",
        "refrigerator.door.closed",
        "refrigerator.notification",
    }
)
_PUSH_CODE_UNSAFE = re.compile(r"[^A-Za-z0-9_.:-]+")


def _normalize_push_code(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _PUSH_CODE_UNSAFE.sub("_", str(value).strip()).strip("_")
    return normalized[:120] or None


@dataclass(frozen=True)
class PushEnvelope:
    device_id: str | None
    message_id: str
    push_type: str | None
    status_report: dict[str, Any] | None
    push_code: str | None
    payload: dict[str, Any]


def _find_first(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, nested in value.items():
            if (
                str(key).replace("_", "").casefold() in keys
                and nested is not None
                and nested != ""
            ):
                return nested
        for nested in value.values():
            found = _find_first(nested, keys)
            if found is not None and found != "":
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_first(nested, keys)
            if found is not None and found != "":
                return found
    return None


def parse_push_message(payload: bytes | str) -> PushEnvelope:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("ThinQ push message exceeds the maximum supported size")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ThinQ push message is not valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise TypeError("ThinQ push message must be a JSON object")
    device_id = _find_first(parsed, {"deviceid"})
    provider_id = _find_first(
        parsed,
        {"eventid", "messageid", "notificationid", "traceid"},
    )
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
    message_id = str(
        provider_id or f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
    )
    push_type_value = parsed.get("pushType")
    push_type = str(push_type_value) if push_type_value is not None else None
    report = parsed.get("report")
    status_report = (
        report
        if push_type == DEVICE_STATUS_MESSAGE and isinstance(report, dict)
        else None
    )
    push_code_value = parsed.get("pushCode")
    push_code = (
        _normalize_push_code(push_code_value)
        if push_type == DEVICE_PUSH_MESSAGE
        else None
    )
    return PushEnvelope(
        device_id=str(device_id) if device_id is not None and device_id != "" else None,
        message_id=message_id,
        push_type=push_type,
        status_report=status_report,
        push_code=push_code,
        payload=parsed,
    )


class ExpiringMessageSet:
    def __init__(
        self, *, ttl_seconds: float = DEFAULT_DEDUP_TTL_SECONDS, maximum: int = 2048
    ):
        self.ttl_seconds = ttl_seconds
        self.maximum = maximum
        self._entries: OrderedDict[str, float] = OrderedDict()

    def add(self, message_id: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - self.ttl_seconds
        while self._entries and next(iter(self._entries.values())) < cutoff:
            self._entries.popitem(last=False)
        if message_id in self._entries:
            return False
        self._entries[message_id] = current
        while len(self._entries) > self.maximum:
            self._entries.popitem(last=False)
        return True


class PushTransport(Protocol):
    async def start(
        self,
        *,
        device_ids: set[str],
        on_message: Callable[[bytes | str], None],
        on_disconnect: Callable[[], None],
    ) -> None: ...

    async def renew(self, *, device_ids: set[str]) -> None: ...

    async def close(self) -> None: ...


TransportFactory = Callable[[dict[str, Any]], Awaitable[PushTransport]]
RefreshCallback = Callable[[str], Awaitable[dict[str, Any]]]
EventCallback = Callable[[str, str, dict[str, Any], str], None]


@dataclass
class _Device:
    entry_id: str
    device_id: str
    device_type: str
    baseline: dict[str, Any] | None = None


@dataclass
class _AccountStream:
    account: dict[str, Any]
    devices: dict[str, _Device] = field(default_factory=dict)
    deduplicator: ExpiringMessageSet = field(default_factory=ExpiringMessageSet)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[Any] | None = None
    transport: PushTransport | None = None
    pending_refreshes: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    refresh_again: set[str] = field(default_factory=set)
    pending_push_codes: dict[str, list[str]] = field(default_factory=dict)
    message_tasks: set[asyncio.Task[Any]] = field(default_factory=set)


class ThinQPushSupervisor:
    def __init__(
        self,
        *,
        transport_factory: TransportFactory,
        refresh: RefreshCallback,
        emit_event: EventCallback,
        renewal_seconds: float = DEFAULT_RENEWAL_SECONDS,
        retry_floor_seconds: float = 1,
        retry_ceiling_seconds: float = 60,
    ) -> None:
        self._transport_factory = transport_factory
        self._refresh = refresh
        self._emit_event = emit_event
        self._renewal_seconds = renewal_seconds
        self._retry_floor_seconds = retry_floor_seconds
        self._retry_ceiling_seconds = retry_ceiling_seconds
        self._streams: dict[str, _AccountStream] = {}

    @staticmethod
    def account_key(entry: dict[str, Any]) -> str:
        client_id = str(entry.get("client_id") or "").strip()
        country = str(entry.get("country_code") or "").strip().upper()
        if not client_id or not country:
            raise ValueError(
                "ThinQ push requires country code and account-scoped client id"
            )
        return f"{country}:{client_id}"

    async def add_device(self, entry: dict[str, Any]) -> None:
        key = self.account_key(entry)
        stream = self._streams.get(key)
        if stream is None:
            stream = _AccountStream(
                account={
                    "access_token": entry["access_token"],
                    "country_code": entry["country_code"],
                    "client_id": entry["client_id"],
                }
            )
            self._streams[key] = stream
        stream.devices[str(entry["id"])] = _Device(
            entry_id=str(entry["id"]),
            device_id=str(entry["device_id"]),
            device_type=str(entry["device_type"]),
        )
        stream.changed.set()
        if stream.task is None or stream.task.done():
            stream.task = asyncio.create_task(self._run(key, stream))

    async def remove_device(self, entry_id: str) -> None:
        for key, stream in list(self._streams.items()):
            if entry_id not in stream.devices:
                continue
            stream.devices.pop(entry_id, None)
            refresh_task = stream.pending_refreshes.get(entry_id)
            if refresh_task and not refresh_task.done():
                refresh_task.cancel()
                await asyncio.gather(refresh_task, return_exceptions=True)
            stream.pending_refreshes.pop(entry_id, None)
            stream.refresh_again.discard(entry_id)
            stream.pending_push_codes.pop(entry_id, None)
            stream.changed.set()
            if not stream.devices:
                stream.stopped.set()
                if stream.task:
                    await stream.task
                self._streams.pop(key, None)
            return

    async def shutdown(self) -> None:
        streams = list(self._streams.values())
        for stream in streams:
            stream.stopped.set()
            stream.changed.set()
        await asyncio.gather(
            *(stream.task for stream in streams if stream.task),
            return_exceptions=True,
        )
        for stream in streams:
            await self._drain_stream_tasks(stream)
        self._streams.clear()

    async def _run(self, key: str, stream: _AccountStream) -> None:
        delay = self._retry_floor_seconds
        first_connection = True
        while stream.devices and not stream.stopped.is_set():
            disconnected = asyncio.Event()
            stream.changed.clear()
            try:
                await self._reconcile(
                    stream, reason="startup" if first_connection else "reconnect"
                )
                transport = await self._transport_factory(stream.account)
                stream.transport = transport
                loop = asyncio.get_running_loop()

                def on_message(
                    payload: bytes | str,
                    *,
                    _loop: asyncio.AbstractEventLoop = loop,
                    _stream: _AccountStream = stream,
                ) -> None:
                    _loop.call_soon_threadsafe(
                        self._start_message_task,
                        _stream,
                        payload,
                    )

                def on_disconnect(
                    *,
                    _loop: asyncio.AbstractEventLoop = loop,
                    _disconnected: asyncio.Event = disconnected,
                ) -> None:
                    _loop.call_soon_threadsafe(_disconnected.set)

                await transport.start(
                    device_ids={device.device_id for device in stream.devices.values()},
                    on_message=on_message,
                    on_disconnect=on_disconnect,
                )
                self._emit_for_all(stream, "thinq.push.connected", {}, "info")
                delay = self._retry_floor_seconds
                first_connection = False
                while True:
                    reason = await self._wait_for_stream_change(stream, disconnected)
                    if reason != "renew":
                        break
                    await transport.renew(
                        device_ids={
                            device.device_id for device in stream.devices.values()
                        }
                    )
                if reason == "disconnect":
                    self._emit_for_all(
                        stream,
                        "thinq.push.disconnected",
                        {"polling_fallback": True},
                        "warning",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - push must degrade to polling
                self._emit_for_all(
                    stream,
                    "thinq.push.unavailable",
                    {"error_type": type(exc).__name__, "polling_fallback": True},
                    "warning",
                )
                try:
                    await asyncio.wait_for(stream.stopped.wait(), timeout=delay)
                except TimeoutError:
                    pass
                delay = min(delay * 2, self._retry_ceiling_seconds)
            finally:
                if stream.transport:
                    try:
                        await stream.transport.close()
                    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                        self._emit_for_all(
                            stream,
                            "thinq.push.close_failed",
                            {"error_type": type(exc).__name__},
                            "warning",
                        )
                    stream.transport = None
        await self._drain_stream_tasks(stream)
        self._streams.pop(key, None)

    def _start_message_task(self, stream: _AccountStream, payload: bytes | str) -> None:
        if stream.stopped.is_set():
            return
        task = asyncio.create_task(self._handle_message(stream, payload))
        stream.message_tasks.add(task)
        task.add_done_callback(stream.message_tasks.discard)

    async def _drain_stream_tasks(self, stream: _AccountStream) -> None:
        tasks = [*stream.message_tasks, *stream.pending_refreshes.values()]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        stream.message_tasks.clear()
        stream.pending_refreshes.clear()

    async def _wait_for_stream_change(
        self,
        stream: _AccountStream,
        disconnected: asyncio.Event,
    ) -> str:
        waiters = {
            asyncio.create_task(stream.stopped.wait()): "stop",
            asyncio.create_task(stream.changed.wait()): "change",
            asyncio.create_task(disconnected.wait()): "disconnect",
        }
        done, pending = await asyncio.wait(
            waiters,
            timeout=self._renewal_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            return "renew"
        return waiters[next(iter(done))]

    async def _handle_message(
        self, stream: _AccountStream, payload: bytes | str
    ) -> None:
        try:
            envelope = parse_push_message(payload)
        except (TypeError, ValueError):
            self._emit_for_all(stream, "thinq.push.message_rejected", {}, "warning")
            return
        if not stream.deduplicator.add(envelope.message_id):
            return
        targets = [
            device
            for device in stream.devices.values()
            if envelope.device_id is None or device.device_id == envelope.device_id
        ]
        for device in targets:
            if envelope.push_code:
                stream.pending_push_codes.setdefault(device.entry_id, []).append(
                    envelope.push_code
                )
            existing = stream.pending_refreshes.get(device.entry_id)
            if existing and not existing.done():
                stream.refresh_again.add(device.entry_id)
                continue
            task = asyncio.create_task(self._refresh_message_hints(stream, device))
            stream.pending_refreshes[device.entry_id] = task

    async def _refresh_message_hints(
        self,
        stream: _AccountStream,
        device: _Device,
    ) -> None:
        try:
            while True:
                stream.refresh_again.discard(device.entry_id)
                push_codes = stream.pending_push_codes.pop(device.entry_id, [])
                await self._refresh_and_emit(
                    stream,
                    device,
                    reason="message",
                    push_codes=push_codes,
                )
                if device.entry_id not in stream.refresh_again:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - polling remains authoritative fallback
            self._emit_event(
                device.entry_id,
                "thinq.push.refresh_failed",
                {"error_type": type(exc).__name__, "polling_fallback": True},
                "warning",
            )
        finally:
            stream.pending_refreshes.pop(device.entry_id, None)

    async def _reconcile(self, stream: _AccountStream, *, reason: str) -> None:
        for device in list(stream.devices.values()):
            await self._refresh_and_emit(stream, device, reason=reason)

    async def _refresh_and_emit(
        self,
        stream: _AccountStream,
        device: _Device,
        *,
        reason: str,
        push_codes: list[str] | None = None,
    ) -> None:
        previous = device.baseline
        current = await self._refresh(device.entry_id)
        device.baseline = current
        if previous is None:
            return
        if device.device_type not in REFRIGERATOR_DEVICE_TYPES:
            if reason == "reconnect":
                self._emit_event(
                    device.entry_id,
                    "thinq.push.reconciled",
                    {"gap_reconciled": True},
                    "info",
                )
            return
        previous_metrics = (
            previous.get("metrics") if isinstance(previous.get("metrics"), dict) else {}
        )
        current_metrics = (
            current.get("metrics") if isinstance(current.get("metrics"), dict) else {}
        )
        previous_door = previous_metrics.get("door_open")
        current_door = current_metrics.get("door_open")
        if isinstance(current_door, bool) and current_door != previous_door:
            self._emit_event(
                device.entry_id,
                "refrigerator.door.opened"
                if current_door
                else "refrigerator.door.closed",
                {"door_open": current_door, "source": "lg_thinq_push"},
                "warning" if current_door else "info",
            )
        previous_notification = previous_metrics.get("notification")
        current_notification = current_metrics.get("notification")
        normalized_notification = _normalize_push_code(current_notification)
        if normalized_notification and current_notification != previous_notification:
            self._emit_event(
                device.entry_id,
                "refrigerator.notification",
                {
                    "code": normalized_notification,
                    "source": "lg_thinq_push",
                },
                "info",
            )
        snapshot_notification = normalized_notification
        for push_code in dict.fromkeys(push_codes or []):
            if push_code == snapshot_notification:
                continue
            self._emit_event(
                device.entry_id,
                "refrigerator.notification",
                {"code": push_code, "source": "lg_thinq_push"},
                "info",
            )
        if reason == "reconnect":
            self._emit_event(
                device.entry_id,
                "thinq.push.reconciled",
                {"gap_reconciled": True},
                "info",
            )

    def _emit_for_all(
        self,
        stream: _AccountStream,
        event_type: str,
        payload: dict[str, Any],
        severity: str,
    ) -> None:
        for device in stream.devices.values():
            self._emit_event(device.entry_id, event_type, payload, severity)


class ThinQSdkPushTransport:
    def __init__(self, account: dict[str, Any]) -> None:
        self._account = account
        self._session: Any = None
        self._api: Any = None
        self._mqtt: Any = None

    async def start(
        self,
        *,
        device_ids: set[str],
        on_message: Callable[[bytes | str], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        from aiohttp import ClientSession
        from thinqconnect.mqtt_client import ThinQMQTTClient
        from thinqconnect.thinq_api import ThinQApi

        self._session = ClientSession()
        self._api = ThinQApi(
            session=self._session,
            access_token=self._account["access_token"],
            country_code=self._account["country_code"],
            client_id=self._account["client_id"],
        )

        def message_callback(_topic, payload, *_args, **_kwargs):
            on_message(payload)

        def disconnect_callback(*_args, **_kwargs):
            on_disconnect()

        self._mqtt = await ThinQMQTTClient(
            self._api,
            self._account["client_id"],
            message_callback,
            on_connection_interrupted=disconnect_callback,
            on_connection_failure=disconnect_callback,
            on_connection_closed=disconnect_callback,
        )
        await self.renew(device_ids=device_ids)
        if not await self._mqtt.async_prepare_mqtt():
            raise RuntimeError("ThinQ MQTT credential preparation failed")
        await self._mqtt.async_connect_mqtt()
        if not self._mqtt.is_connected:
            raise RuntimeError("ThinQ MQTT connection failed")

    async def renew(self, *, device_ids: set[str]) -> None:
        if self._api is None:
            raise RuntimeError("ThinQ MQTT API is not initialized")
        from thinqconnect import ThinQAPIErrorCodes, ThinQAPIException

        for device_id in sorted(device_ids):
            await self._api.async_post_event_subscribe(device_id)
            try:
                await self._api.async_post_push_subscribe(device_id)
            except ThinQAPIException as exc:
                if exc.code != ThinQAPIErrorCodes.ALREADY_SUBSCRIBED_PUSH:
                    raise

    async def close(self) -> None:
        try:
            if (
                self._mqtt is not None
                and getattr(self._mqtt, "_mqtt_connection", None) is not None
            ):
                try:
                    await self._mqtt.async_disconnect()
                finally:
                    connection = getattr(self._mqtt, "_mqtt_connection", None)
                    if connection is not None:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None,
                            lambda: connection.disconnect().result(),
                        )
        finally:
            if self._session is not None:
                await self._session.close()
            self._session = None
            self._api = None
            self._mqtt = None


async def create_sdk_push_transport(account: dict[str, Any]) -> PushTransport:
    return ThinQSdkPushTransport(account)
