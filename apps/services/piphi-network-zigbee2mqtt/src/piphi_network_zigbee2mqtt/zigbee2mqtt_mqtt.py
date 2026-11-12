from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Any
from urllib.parse import unquote, urlparse

from .bridge_models import (
    DeviceListResponse,
    MqttSettings,
    NetworkMapLink,
    NetworkMapNode,
    NetworkMapResponse,
    PermitJoinResponse,
    Zigbee2MqttDevice,
)
from .broker_health import parse_mqtt_endpoint


class Zigbee2MqttMqttError(RuntimeError):
    pass


class Zigbee2MqttMqttClient:
    def __init__(
        self,
        *,
        mqtt: MqttSettings,
        timeout_seconds: float = 8.0,
        mqtt_module: Any | None = None,
    ) -> None:
        self.mqtt = mqtt
        self.timeout_seconds = timeout_seconds
        self._mqtt_module = mqtt_module

    async def list_devices(self, *, dry_run: bool = False) -> DeviceListResponse:
        response_topic = f"{self.mqtt.base_topic}/bridge/devices"
        if dry_run:
            return DeviceListResponse(
                ok=True,
                status="planned",
                devices=[],
                server=self.mqtt.server,
                base_topic=self.mqtt.base_topic,
                response_topic=response_topic,
            )
        raw = await self._read_json_topic(response_topic)
        devices = _extract_devices(raw)
        return DeviceListResponse(
            ok=True,
            status="ok",
            devices=devices,
            server=self.mqtt.server,
            base_topic=self.mqtt.base_topic,
            response_topic=response_topic,
            raw=raw,
        )

    async def permit_join(
        self,
        *,
        value: bool,
        time: int,
        device: str | None = None,
        dry_run: bool = False,
    ) -> PermitJoinResponse:
        request_topic = f"{self.mqtt.base_topic}/bridge/request/permit_join"
        response_topic = f"{self.mqtt.base_topic}/bridge/response/permit_join"
        payload: dict[str, Any] = {"value": value, "time": time}
        if device:
            payload["device"] = device
        if dry_run:
            return PermitJoinResponse(
                ok=True,
                status="planned",
                value=value,
                time=time,
                device=device,
                server=self.mqtt.server,
                base_topic=self.mqtt.base_topic,
                request_topic=request_topic,
                response_topic=response_topic,
            )
        raw = await self._request_response(
            request_topic=request_topic,
            response_topic=response_topic,
            payload=payload,
        )
        return PermitJoinResponse(
            ok=_response_ok(raw),
            status=str(raw.get("status") or "ok"),
            value=value,
            time=time,
            device=device,
            server=self.mqtt.server,
            base_topic=self.mqtt.base_topic,
            request_topic=request_topic,
            response_topic=response_topic,
            transaction=_response_transaction(raw),
            message=_response_message(raw),
            raw=raw,
        )

    async def network_map(self, *, routes: bool = False, dry_run: bool = False) -> NetworkMapResponse:
        request_topic = f"{self.mqtt.base_topic}/bridge/request/networkmap"
        response_topic = f"{self.mqtt.base_topic}/bridge/response/networkmap"
        if dry_run:
            return NetworkMapResponse(
                ok=True,
                status="planned",
                routes_included=routes,
                server=self.mqtt.server,
                base_topic=self.mqtt.base_topic,
                request_topic=request_topic,
                response_topic=response_topic,
            )
        raw = await self._request_response(
            request_topic=request_topic,
            response_topic=response_topic,
            payload={"type": "raw", "routes": routes},
        )
        nodes, links = _extract_network_map(raw)
        return NetworkMapResponse(
            ok=_response_ok(raw),
            status=str(raw.get("status") or "ok"),
            nodes=nodes,
            links=links,
            routes_included=routes,
            server=self.mqtt.server,
            base_topic=self.mqtt.base_topic,
            request_topic=request_topic,
            response_topic=response_topic,
            transaction=_response_transaction(raw),
            message=_response_message(raw),
        )

    async def _request_response(
        self,
        *,
        request_topic: str,
        response_topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_response_sync,
            request_topic=request_topic,
            response_topic=response_topic,
            payload=payload,
        )

    async def _read_json_topic(self, topic: str) -> Any:
        return await asyncio.to_thread(self._read_json_topic_sync, topic=topic)

    def _read_json_topic_sync(self, *, topic: str) -> Any:
        mqtt_module = self._mqtt_module or _load_paho_mqtt()
        client_id = f"piphi-z2m-read-{uuid.uuid4()}"
        response_event = threading.Event()
        response_payload: dict[str, Any] = {}
        error: list[str] = []

        client = _create_client(mqtt_module, client_id=client_id)
        username, password = _mqtt_credentials(self.mqtt)
        if username:
            client.username_pw_set(username, password)

        def on_connect(client, _userdata, _flags, reason_code, _properties=None):
            if _reason_code_failed(reason_code):
                error.append(f"mqtt_connect_failed:{reason_code}")
                response_event.set()
                return
            client.subscribe(topic)

        def on_message(_client, _userdata, message):
            try:
                decoded = json.loads(message.payload.decode("utf-8"))
            except Exception as exc:
                error.append(f"invalid_json_response:{exc}")
                response_event.set()
                return
            response_payload["value"] = decoded
            response_event.set()

        client.on_connect = on_connect
        client.on_message = on_message
        return _connect_and_wait(
            client=client,
            server=self.mqtt.server,
            timeout_seconds=self.timeout_seconds,
            response_event=response_event,
            response_payload=response_payload,
            error=error,
            empty_message=f"Empty response from {topic}.",
            timeout_message=f"Timed out waiting for retained {topic}.",
        )

    def _request_response_sync(
        self,
        *,
        request_topic: str,
        response_topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        mqtt_module = self._mqtt_module or _load_paho_mqtt()
        transaction = str(uuid.uuid4())
        request_payload = {**payload, "transaction": transaction}
        response_event = threading.Event()
        response_payload: dict[str, Any] = {}
        error: list[str] = []

        client = _create_client(mqtt_module, client_id=f"piphi-z2m-{transaction}")
        username, password = _mqtt_credentials(self.mqtt)
        if username:
            client.username_pw_set(username, password)

        def on_connect(client, _userdata, _flags, reason_code, _properties=None):
            if _reason_code_failed(reason_code):
                error.append(f"mqtt_connect_failed:{reason_code}")
                response_event.set()
                return
            client.subscribe(response_topic)

        def on_subscribe(client, _userdata, _mid, _reason_codes=None, _properties=None):
            client.publish(request_topic, json.dumps(request_payload, separators=(",", ":")))

        def on_message(_client, _userdata, message):
            try:
                decoded = json.loads(message.payload.decode("utf-8"))
            except Exception as exc:
                error.append(f"invalid_json_response:{exc}")
                response_event.set()
                return
            if not isinstance(decoded, dict):
                error.append("unexpected_response_shape")
                response_event.set()
                return
            response_transaction = _response_transaction(decoded)
            if response_transaction and response_transaction != transaction:
                return
            response_payload.update(decoded)
            response_event.set()

        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        return _connect_and_wait(
            client=client,
            server=self.mqtt.server,
            timeout_seconds=self.timeout_seconds,
            response_event=response_event,
            response_payload=response_payload,
            error=error,
            empty_message=f"Empty response from {response_topic}.",
            timeout_message=f"Timed out waiting for {response_topic}.",
        )


def resolve_mqtt_settings(
    *,
    current: MqttSettings | None,
    server: str | None,
    base_topic: str | None,
) -> MqttSettings:
    if current is None and not server:
        raise ValueError("MQTT server is required before bridge config is rendered.")
    source = current or MqttSettings(server=server or "mqtt://127.0.0.1:1883")
    return MqttSettings(
        server=server or source.server,
        user=source.user,
        password=source.password,
        base_topic=base_topic or source.base_topic,
    )


def _load_paho_mqtt():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise Zigbee2MqttMqttError("paho-mqtt is required for Zigbee2MQTT MQTT operations.") from exc
    return mqtt


def _create_client(mqtt_module: Any, *, client_id: str):
    callback_api_version = getattr(mqtt_module, "CallbackAPIVersion", None)
    if callback_api_version is not None:
        return mqtt_module.Client(callback_api_version.VERSION2, client_id=client_id)
    return mqtt_module.Client(client_id=client_id)


def _connect_and_wait(
    *,
    client: Any,
    server: str,
    timeout_seconds: float,
    response_event: threading.Event,
    response_payload: dict[str, Any],
    error: list[str],
    empty_message: str,
    timeout_message: str,
) -> Any:
    host, port = parse_mqtt_endpoint(server)
    try:
        client.connect(host, port, keepalive=max(5, int(timeout_seconds)))
        client.loop_start()
        if not response_event.wait(timeout_seconds):
            raise Zigbee2MqttMqttError(timeout_message)
        if error:
            raise Zigbee2MqttMqttError(error[-1])
        if not response_payload:
            raise Zigbee2MqttMqttError(empty_message)
        if "value" in response_payload:
            return response_payload["value"]
        return response_payload
    except Zigbee2MqttMqttError:
        raise
    except Exception as exc:
        raise Zigbee2MqttMqttError(str(exc)) from exc
    finally:
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass


def _mqtt_credentials(settings: MqttSettings) -> tuple[str | None, str | None]:
    parsed = urlparse(settings.server if "://" in settings.server else f"mqtt://{settings.server}")
    username = settings.user or (unquote(parsed.username) if parsed.username else None)
    password = settings.password or (unquote(parsed.password) if parsed.password else None)
    return username, password


def _reason_code_failed(reason_code: Any) -> bool:
    value = getattr(reason_code, "value", reason_code)
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return str(reason_code).lower() not in {"success", "0"}


def _extract_devices(raw: Any) -> list[Zigbee2MqttDevice]:
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, dict):
            candidate = data.get("devices")
        elif data is not None:
            candidate = data
        else:
            candidate = raw.get("devices")
    else:
        candidate = raw
    if not isinstance(candidate, list):
        return []
    return [
        Zigbee2MqttDevice.model_validate(item)
        for item in candidate
        if isinstance(item, dict) and item.get("friendly_name")
    ]


def _extract_network_map(raw: dict[str, Any]) -> tuple[list[NetworkMapNode], list[NetworkMapLink]]:
    data = raw.get("data") if isinstance(raw, dict) else None
    value = data.get("value") if isinstance(data, dict) else None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise Zigbee2MqttMqttError("Zigbee2MQTT returned an invalid raw network map.") from exc
    if not isinstance(value, dict):
        raise Zigbee2MqttMqttError("Zigbee2MQTT returned no raw network map.")

    raw_nodes = value.get("nodes")
    raw_links = value.get("links")
    if not isinstance(raw_nodes, list) or not isinstance(raw_links, list):
        raise Zigbee2MqttMqttError("Zigbee2MQTT returned an unexpected network map shape.")
    if len(raw_nodes) > 500 or len(raw_links) > 4000:
        raise Zigbee2MqttMqttError("Zigbee2MQTT network map exceeds PiPhi safety limits.")

    nodes: list[NetworkMapNode] = []
    aliases: dict[str, str] = {}
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, dict):
            continue
        ieee = _bounded_text(item.get("ieeeAddr") or item.get("ieee_address"))
        network_address = _bounded_int(item.get("networkAddress") or item.get("network_address"), 0, 65535)
        node_id = ieee or (str(network_address) if network_address is not None else f"node-{index}")
        friendly_name = _bounded_text(item.get("friendlyName") or item.get("friendly_name")) or node_id
        node = NetworkMapNode(
            id=node_id,
            friendly_name=friendly_name,
            type=_bounded_text(item.get("type")) or "Unknown",
            ieee_address=ieee,
            network_address=network_address,
            manufacturer=_bounded_text(item.get("manufacturerName") or item.get("manufacturer")),
            model=_bounded_text(item.get("modelID") or item.get("model")),
        )
        nodes.append(node)
        for alias in (node_id, ieee, friendly_name, str(network_address) if network_address is not None else None):
            if alias:
                aliases[str(alias)] = node_id

    links: list[NetworkMapLink] = []
    for item in raw_links:
        if not isinstance(item, dict):
            continue
        source = _network_map_endpoint(item.get("source"), aliases)
        target = _network_map_endpoint(item.get("target"), aliases)
        if not source or not target:
            continue
        raw_routes = item.get("routes") if isinstance(item.get("routes"), list) else []
        routes = [route for route in (_bounded_int(value, 0, 65535) for value in raw_routes[:128]) if route is not None]
        links.append(
            NetworkMapLink(
                source=source,
                target=target,
                link_quality=_bounded_int(item.get("linkquality") or item.get("linkQuality"), 0, 255),
                depth=_bounded_int(item.get("depth"), 0, 255),
                routes=routes,
            )
        )
    return nodes, links


def _network_map_endpoint(value: Any, aliases: dict[str, str]) -> str | None:
    if isinstance(value, dict):
        value = value.get("ieeeAddr") or value.get("ieee_address") or value.get("id") or value.get("networkAddress")
    token = _bounded_text(value)
    return aliases.get(token, token) if token else None


def _bounded_text(value: Any, limit: int = 256) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\x00", "").strip()
    return token[:limit] or None


def _bounded_int(value: Any, minimum: int, maximum: int) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if minimum <= parsed <= maximum else None


def _response_ok(raw: dict[str, Any]) -> bool:
    return str(raw.get("status") or "ok").lower() in {"ok", "success"}


def _response_transaction(raw: dict[str, Any]) -> str | None:
    value = raw.get("transaction")
    if value is None and isinstance(raw.get("data"), dict):
        value = raw["data"].get("transaction")
    return str(value) if value is not None else None


def _response_message(raw: dict[str, Any]) -> str | None:
    for key in ("error", "message"):
        value = raw.get(key)
        if value:
            return str(value)
    return None
