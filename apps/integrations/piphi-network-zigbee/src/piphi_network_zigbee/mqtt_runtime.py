from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse


STATE_FIELDS = {
    "action": "action",
    "availability": "availability",
    "battery_percent": "battery",
    "battery_low": "battery_low",
    "brightness_percent": "brightness",
    "carbon_monoxide": "carbon_monoxide",
    "color_temperature_mired": "color_temp",
    "contact_open": "contact",
    "current_a": "current",
    "energy_kwh": "energy",
    "gas": "gas",
    "humidity_percent": "humidity",
    "illuminance_lux": "illuminance",
    "linkquality": "linkquality",
    "occupancy": "occupancy",
    "position_percent": "position",
    "power_w": "power",
    "pressure_hpa": "pressure",
    "smoke": "smoke",
    "state": "state",
    "tamper": "tamper",
    "temperature_c": "temperature",
    "voltage_v": "voltage",
    "water_leak": "water_leak",
}


class ZigbeeMqttError(RuntimeError):
    pass


@dataclass(frozen=True)
class ZigbeeMqttSubscription:
    topic: str
    config_id: str
    device_id: str
    kind: str = "state"


class ZigbeeMqttClient:
    def __init__(
        self,
        *,
        server: str,
        timeout_seconds: float = 5.0,
        mqtt_module: Any | None = None,
    ) -> None:
        self.server = server
        self.timeout_seconds = timeout_seconds
        self._mqtt_module = mqtt_module

    async def publish_json(self, topic: str, payload: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {"ok": True, "status": "planned", "topic": topic, "payload": payload}
        return await asyncio.to_thread(self._publish_json_sync, topic=topic, payload=payload)

    async def read_json_topic(self, topic: str, *, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {"ok": True, "status": "planned", "topic": topic, "payload": {}}
        payload = await asyncio.to_thread(self._read_json_topic_sync, topic=topic)
        return {"ok": True, "status": "ok", "topic": topic, "payload": payload}

    def _publish_json_sync(self, *, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        mqtt_module = self._mqtt_module or _load_paho_mqtt()
        client = _create_client(mqtt_module, client_id=f"piphi-zigbee-pub-{uuid.uuid4()}")
        _set_credentials(client, self.server)
        host, port = parse_mqtt_endpoint(self.server)
        encoded_payload = json.dumps(payload, separators=(",", ":"))
        try:
            client.connect(host, port, keepalive=max(5, int(self.timeout_seconds)))
            client.loop_start()
            publish_info = client.publish(topic, encoded_payload)
            wait_for_publish = getattr(publish_info, "wait_for_publish", None)
            if callable(wait_for_publish):
                wait_for_publish(timeout=self.timeout_seconds)
            rc = getattr(publish_info, "rc", 0)
            if int(rc or 0) != 0:
                raise ZigbeeMqttError(f"MQTT publish failed with rc={rc}.")
            return {"ok": True, "status": "published", "topic": topic, "payload": payload}
        except ZigbeeMqttError:
            raise
        except Exception as exc:
            raise ZigbeeMqttError(str(exc)) from exc
        finally:
            _disconnect(client)

    def _read_json_topic_sync(self, *, topic: str) -> dict[str, Any]:
        mqtt_module = self._mqtt_module or _load_paho_mqtt()
        response_event = threading.Event()
        response_payload: dict[str, Any] = {}
        error: list[str] = []

        client = _create_client(mqtt_module, client_id=f"piphi-zigbee-read-{uuid.uuid4()}")
        _set_credentials(client, self.server)

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
            if not isinstance(decoded, dict):
                error.append("unexpected_response_shape")
                response_event.set()
                return
            response_payload.update(decoded)
            response_event.set()

        client.on_connect = on_connect
        client.on_message = on_message
        host, port = parse_mqtt_endpoint(self.server)
        try:
            client.connect(host, port, keepalive=max(5, int(self.timeout_seconds)))
            client.loop_start()
            if not response_event.wait(self.timeout_seconds):
                raise ZigbeeMqttError(f"Timed out waiting for retained {topic}.")
            if error:
                raise ZigbeeMqttError(error[-1])
            return response_payload
        except ZigbeeMqttError:
            raise
        except Exception as exc:
            raise ZigbeeMqttError(str(exc)) from exc
        finally:
            _disconnect(client)


class ZigbeeMqttSubscriber:
    def __init__(
        self,
        *,
        server: str,
        subscriptions: list[ZigbeeMqttSubscription],
        on_payload: Callable[[ZigbeeMqttSubscription, dict[str, Any]], None],
        mqtt_module: Any | None = None,
    ) -> None:
        self.server = server
        self.subscriptions = subscriptions
        self.on_payload = on_payload
        self._mqtt_module = mqtt_module
        self._client: Any | None = None
        self.status = "stopped"
        self.message: str | None = None
        self.started_at: datetime | None = None

    @property
    def topics(self) -> list[str]:
        return [subscription.topic for subscription in self.subscriptions]

    def start(self) -> None:
        if not self.subscriptions:
            self.status = "stopped"
            self.message = "no subscriptions"
            return
        mqtt_module = self._mqtt_module or _load_paho_mqtt()
        client = _create_client(mqtt_module, client_id=f"piphi-zigbee-sub-{uuid.uuid4()}")
        _set_credentials(client, self.server)
        topic_map = {subscription.topic: subscription for subscription in self.subscriptions}

        def on_connect(client, _userdata, _flags, reason_code, _properties=None):
            if _reason_code_failed(reason_code):
                self.status = "error"
                self.message = f"mqtt_connect_failed:{reason_code}"
                return
            for topic in topic_map:
                client.subscribe(topic)
            self.status = "running"
            self.message = None

        def on_message(_client, _userdata, message):
            subscription = topic_map.get(str(message.topic))
            if subscription is None:
                return
            payload = decode_zigbee2mqtt_message(message.payload, kind=subscription.kind)
            if payload is None:
                return
            self.on_payload(subscription, payload)

        host, port = parse_mqtt_endpoint(self.server)
        try:
            client.on_connect = on_connect
            client.on_message = on_message
            reconnect_delay_set = getattr(client, "reconnect_delay_set", None)
            if callable(reconnect_delay_set):
                reconnect_delay_set(min_delay=1, max_delay=30)
            client.connect(host, port, keepalive=30)
            client.loop_start()
            self._client = client
            self.status = "starting"
            self.started_at = datetime.now(timezone.utc)
        except Exception as exc:
            self.status = "error"
            self.message = str(exc)
            _disconnect(client)
            raise ZigbeeMqttError(str(exc)) from exc

    def stop(self) -> None:
        if self._client is not None:
            _disconnect(self._client)
        self._client = None
        self.status = "stopped"

    def snapshot(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "status": self.status,
            "message": self.message,
            "topics": self.topics,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }


def command_to_mqtt(entry: dict[str, Any], command_name: str, params: dict[str, Any]) -> dict[str, Any]:
    topic = str(entry.get("mqtt_topic") or "").strip().rstrip("/")
    if not topic:
        raise ValueError("configured Zigbee device is missing mqtt_topic")
    if command_name == "refresh":
        return {"topic": f"{topic}/get", "payload": _refresh_payload(entry)}
    if command_name == "set_state":
        return {"topic": f"{topic}/set", "payload": {"state": _state_payload_value(params)}}
    if command_name == "set_brightness":
        return {"topic": f"{topic}/set", "payload": {"brightness": _brightness_payload_value(params)}}
    if command_name == "set_color_temperature":
        return {"topic": f"{topic}/set", "payload": {"color_temp": _color_temp_payload_value(params)}}
    raise ValueError(f"unsupported Zigbee MQTT command: {command_name}")


def normalize_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {"connected": True, "zigbee_payload": payload}
    for capability, zigbee_property in STATE_FIELDS.items():
        if zigbee_property in payload:
            state[capability] = _normalize_state_value(capability, payload[zigbee_property])
    return state


def subscriptions_for_entry(entry: dict[str, Any]) -> list[ZigbeeMqttSubscription]:
    topic = str(entry.get("mqtt_topic") or "").strip().rstrip("/")
    config_id = str(entry.get("config_id") or entry.get("id") or "").strip()
    device_id = str(entry.get("device_id") or config_id).strip()
    if not topic or not config_id:
        return []
    return [
        ZigbeeMqttSubscription(topic=topic, config_id=config_id, device_id=device_id, kind="state"),
        ZigbeeMqttSubscription(topic=f"{topic}/availability", config_id=config_id, device_id=device_id, kind="availability"),
    ]


def decode_zigbee2mqtt_message(payload: bytes, *, kind: str) -> dict[str, Any] | None:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if kind == "availability":
        try:
            decoded = json.loads(text)
        except ValueError:
            decoded = text
        if isinstance(decoded, dict):
            value = decoded.get("state") or decoded.get("availability") or decoded.get("status")
        else:
            value = decoded
        return {"availability": value}
    try:
        decoded = json.loads(text)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def parse_mqtt_endpoint(server: str) -> tuple[str, int]:
    token = str(server or "").strip()
    if not token:
        raise ValueError("MQTT server is required.")
    parsed = urlparse(token if "://" in token else f"mqtt://{token}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"MQTT server is missing a host: {server}")
    if parsed.port:
        return host, parsed.port
    if parsed.scheme == "mqtts":
        return host, 8883
    if parsed.scheme in {"mqtt", ""}:
        return host, 1883
    raise ValueError(f"Unsupported MQTT scheme: {parsed.scheme}")


def _refresh_payload(entry: dict[str, Any]) -> dict[str, str]:
    readable_properties = _readable_expose_properties(entry)
    if readable_properties:
        return {property_name: "" for property_name in sorted(set(readable_properties))}
    capabilities = set(entry.get("capabilities") or [])
    readable_properties = [
        zigbee_property
        for capability, zigbee_property in STATE_FIELDS.items()
        if capability in capabilities and capability not in {"availability", "linkquality"}
    ]
    if not readable_properties:
        readable_properties = ["state"]
    return {property_name: "" for property_name in sorted(set(readable_properties))}


def _readable_expose_properties(entry: dict[str, Any]) -> list[str]:
    properties: list[str] = []
    for expose in entry.get("exposes") or []:
        if not isinstance(expose, dict):
            continue
        property_name = str(expose.get("property") or "").strip()
        if not property_name or property_name in {"availability", "linkquality"}:
            continue
        access = expose.get("access")
        if isinstance(access, dict) and access.get("get") is False:
            continue
        properties.append(property_name)
    return properties


def _state_payload_value(params: dict[str, Any]) -> str:
    raw_value = params.get("state", params.get("value", params.get("on")))
    if isinstance(raw_value, bool):
        return "ON" if raw_value else "OFF"
    token = str(raw_value or "").strip().upper()
    if token in {"ON", "OFF", "TOGGLE"}:
        return token
    raise ValueError("set_state requires state/value/on as ON, OFF, TOGGLE, or a boolean")


def _brightness_payload_value(params: dict[str, Any]) -> int:
    raw_value = params.get("brightness", params.get("brightness_percent", params.get("value")))
    if raw_value is None:
        raise ValueError("set_brightness requires brightness, brightness_percent, or value")
    value = float(raw_value)
    if 0 <= value <= 100 and "brightness" not in params:
        return round(value * 254 / 100)
    return max(0, min(254, round(value)))


def _color_temp_payload_value(params: dict[str, Any]) -> int:
    raw_value = params.get("color_temp", params.get("color_temperature_mired", params.get("value")))
    if raw_value is None:
        raise ValueError("set_color_temperature requires color_temp, color_temperature_mired, or value")
    return round(float(raw_value))


def _normalize_state_value(capability: str, value: Any) -> Any:
    if capability == "contact_open":
        # Zigbee2MQTT's contact property means the magnetic contact is closed
        # when true. PiPhi exposes the inverse semantic: whether it is open.
        if isinstance(value, bool):
            return not value
        token = str(value).strip().lower()
        if token in {"true", "1", "closed", "on"}:
            return False
        if token in {"false", "0", "open", "off"}:
            return True
        return value
    if capability in {
        "availability",
        "battery_low",
        "carbon_monoxide",
        "gas",
        "occupancy",
        "smoke",
        "tamper",
        "water_leak",
    }:
        if isinstance(value, bool):
            return value
        token = str(value).strip().lower()
        if capability == "availability":
            return token in {"online", "true", "1", "available"}
        return token in {"true", "1", "open", "on", "occupied"}
    if capability == "state":
        if isinstance(value, bool):
            return value
        token = str(value).strip().upper()
        if token in {"ON", "OFF"}:
            return token == "ON"
        return value
    if capability == "brightness_percent":
        return round(float(value) * 100 / 254)
    if capability in {
        "battery_percent",
        "color_temperature_mired",
        "current_a",
        "energy_kwh",
        "humidity_percent",
        "illuminance_lux",
        "linkquality",
        "position_percent",
        "power_w",
        "pressure_hpa",
        "temperature_c",
        "voltage_v",
    }:
        return value
    return value


def _load_paho_mqtt():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise ZigbeeMqttError("paho-mqtt is required for Zigbee MQTT operations.") from exc
    return mqtt


def _create_client(mqtt_module: Any, *, client_id: str):
    callback_api_version = getattr(mqtt_module, "CallbackAPIVersion", None)
    if callback_api_version is not None:
        return mqtt_module.Client(callback_api_version.VERSION2, client_id=client_id)
    return mqtt_module.Client(client_id=client_id)


def _set_credentials(client: Any, server: str) -> None:
    parsed = urlparse(server if "://" in server else f"mqtt://{server}")
    if parsed.username:
        client.username_pw_set(unquote(parsed.username), unquote(parsed.password) if parsed.password else None)


def _reason_code_failed(reason_code: Any) -> bool:
    value = getattr(reason_code, "value", reason_code)
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return str(reason_code).lower() not in {"success", "0"}


def _disconnect(client: Any) -> None:
    try:
        client.loop_stop()
    except Exception:
        pass
    try:
        client.disconnect()
    except Exception:
        pass
