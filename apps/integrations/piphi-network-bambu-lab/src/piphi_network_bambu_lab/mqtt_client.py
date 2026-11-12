"""Read-only Bambu LAN MQTT session with CA and printer-serial TLS checks."""

from __future__ import annotations

import json
import secrets
import ssl
from collections.abc import Callable
from importlib.resources import files
from time import monotonic
from typing import Any

MAX_REPORT_BYTES = 65_536
PUSHALL_MIN_INTERVAL_SECONDS = 300


def peer_names(certificate: dict[str, Any]) -> set[str]:
    names = {
        str(value).upper()
        for kind, value in certificate.get("subjectAltName", ())
        if kind == "DNS"
    }
    for distinguished_name in certificate.get("subject", ()):
        for key, value in distinguished_name:
            if key == "commonName":
                names.add(str(value).upper())
    return names


class PrinterMqttSession:
    def __init__(
        self,
        *,
        host: str,
        serial: str,
        access_code: str,
        on_report: Callable[[dict[str, Any]], None],
        on_offline: Callable[[], None],
    ) -> None:
        self.host = host
        self.serial = serial.upper()
        self._access_code = access_code
        self._on_report = on_report
        self._on_offline = on_offline
        self._client: Any = None
        self.connected = False
        self._last_pushall: float | None = None

    @property
    def report_topic(self) -> str:
        return f"device/{self.serial}/report"

    @property
    def request_topic(self) -> str:
        return f"device/{self.serial}/request"

    def verify_socket(self, sock: Any) -> None:
        certificate = sock.getpeercert()
        if not isinstance(certificate, dict) or self.serial not in peer_names(certificate):
            raise ssl.CertificateError("printer certificate does not match configured serial")

    def start(self) -> None:
        import paho.mqtt.client as mqtt

        ca_path = files("piphi_network_bambu_lab").joinpath("bbl_ca.pem")
        context = ssl.create_default_context(cafile=str(ca_path))
        # The printer's certificate identifies its serial, not its LAN IP.
        # Paho completes TLS before on_socket_open; verify that serial there
        # before MQTT sends the access code.
        context.check_hostname = False
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"piphi-bambu-{secrets.token_hex(6)}",
        )
        # A serial mismatch must abort reconnect before _send_connect.
        client.suppress_exceptions = False
        client.tls_set_context(context)
        client.username_pw_set("bblp", self._access_code)
        client.reconnect_delay_set(min_delay=5, max_delay=60)
        client.on_socket_open = lambda _client, _userdata, sock: self.verify_socket(sock)
        client.on_connect = self._handle_connect
        client.on_connect_fail = lambda _client, _userdata: self._handle_disconnect()
        client.on_disconnect = lambda *_args: self._handle_disconnect()
        client.on_message = self._handle_message
        self._client = client
        client.connect_async(self.host, 8883, keepalive=30)
        client.loop_start()

    def stop(self) -> None:
        client, self._client = self._client, None
        self.connected = False
        if client is not None:
            client.disconnect()
            client.loop_stop()

    def _handle_connect(self, client: Any, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
        if reason_code != 0:
            self._handle_disconnect()
            return
        self.connected = True
        client.subscribe(self.report_topic, qos=0)
        self.request_full_status()

    def _handle_disconnect(self) -> None:
        self.connected = False
        self._on_offline()

    def _handle_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        if message.topic != self.report_topic or len(message.payload) > MAX_REPORT_BYTES:
            return
        try:
            payload = json.loads(message.payload)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(payload, dict):
            self._on_report(payload)

    def request_full_status(self) -> bool:
        if not self.connected or self._client is None:
            return False
        now = monotonic()
        if self._last_pushall is not None and now - self._last_pushall < PUSHALL_MIN_INTERVAL_SECONDS:
            return False
        payload = {
            "pushing": {
                "sequence_id": "0",
                "command": "pushall",
                "version": 1,
                "push_target": 1,
            }
        }
        result = self._client.publish(self.request_topic, json.dumps(payload), qos=0)
        if result.rc != 0:
            return False
        self._last_pushall = now
        return True
