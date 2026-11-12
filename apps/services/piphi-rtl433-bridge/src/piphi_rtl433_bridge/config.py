from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import shlex


@dataclass(frozen=True)
class BridgeConfig:
    http_forward_enabled: bool
    runtime_ingest_url: str
    radio_band: str
    frequency: str
    rtl_sdr_device: str
    receiver_gain: str
    protocol_ids: tuple[str, ...]
    raw_rtl433_command: str | None
    rtl433_command: list[str]
    forward_timeout_seconds: float
    retry_delay_seconds: float
    startup_delay_seconds: float
    extra_headers: dict[str, str]
    mqtt_enabled: bool
    mqtt_hostname: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_client_id: str | None
    mqtt_qos: int
    mqtt_topic_root: str


DEFAULT_RUNTIME_INGEST_URL = "http://127.0.0.1:8090/ingest/rtl433"
DEFAULT_RADIO_BAND = "433mhz"
DEFAULT_FREQUENCY = "433.92M"
DEFAULT_RTL433_COMMAND = ""
DEFAULT_MQTT_TOPIC_ROOT = "piphi/sources/rtl433"
RADIO_BAND_PRESETS = {
    "315mhz": "315M",
    "433mhz": DEFAULT_FREQUENCY,
    "868mhz": "868M",
    "915mhz": "915M",
}


def load_bridge_config() -> BridgeConfig:
    return build_bridge_config(
        http_forward_enabled=_parse_bool_env("HTTP_FORWARD_ENABLED", True),
        runtime_ingest_url=os.getenv("RUNTIME_INGEST_URL", DEFAULT_RUNTIME_INGEST_URL),
        radio_band=os.getenv("RADIO_BAND", DEFAULT_RADIO_BAND),
        custom_frequency=os.getenv("CUSTOM_FREQUENCY", ""),
        rtl_sdr_device=os.getenv("RTLSDR_DEVICE", "auto"),
        receiver_gain=os.getenv("RECEIVER_GAIN", "auto"),
        protocol_ids_text=os.getenv("RTL433_PROTOCOLS", ""),
        rtl433_command_text=os.getenv("RTL433_COMMAND", DEFAULT_RTL433_COMMAND),
        forward_timeout_seconds=float(os.getenv("FORWARD_TIMEOUT_SECONDS", "10")),
        retry_delay_seconds=float(os.getenv("RETRY_DELAY_SECONDS", "5")),
        startup_delay_seconds=float(os.getenv("STARTUP_DELAY_SECONDS", "2")),
        extra_headers_json=os.getenv("BRIDGE_EXTRA_HEADERS_JSON", ""),
        mqtt_enabled=_parse_bool_env("MQTT_ENABLED", False),
        mqtt_hostname=os.getenv("MQTT_HOSTNAME", "127.0.0.1"),
        mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
        mqtt_username=os.getenv("MQTT_USERNAME") or None,
        mqtt_password=os.getenv("MQTT_PASSWORD") or None,
        mqtt_client_id=os.getenv("MQTT_CLIENT_ID") or None,
        mqtt_qos=int(os.getenv("MQTT_QOS", "0")),
        mqtt_topic_root=os.getenv("MQTT_TOPIC_ROOT", DEFAULT_MQTT_TOPIC_ROOT),
    )


def build_bridge_config(
    *,
    http_forward_enabled: bool,
    runtime_ingest_url: str,
    radio_band: str = DEFAULT_RADIO_BAND,
    custom_frequency: str = "",
    rtl_sdr_device: str = "auto",
    receiver_gain: str = "auto",
    protocol_ids_text: str = "",
    protocol_ids: tuple[str, ...] | list[str] | None = None,
    rtl433_command_text: str = DEFAULT_RTL433_COMMAND,
    forward_timeout_seconds: float,
    retry_delay_seconds: float,
    startup_delay_seconds: float,
    extra_headers_json: str = "",
    extra_headers: dict[str, str] | None = None,
    mqtt_enabled: bool = False,
    mqtt_hostname: str = "127.0.0.1",
    mqtt_port: int = 1883,
    mqtt_username: str | None = None,
    mqtt_password: str | None = None,
    mqtt_client_id: str | None = None,
    mqtt_qos: int = 0,
    mqtt_topic_root: str = DEFAULT_MQTT_TOPIC_ROOT,
) -> BridgeConfig:
    merged_headers = parse_extra_headers(extra_headers_json)
    if extra_headers:
        merged_headers.update(extra_headers)
    normalized_protocol_ids = tuple(protocol_ids or parse_protocol_ids(protocol_ids_text))
    frequency = resolve_frequency(radio_band=radio_band, custom_frequency=custom_frequency)
    raw_rtl433_command = rtl433_command_text.strip() or None
    rtl433_command = build_rtl433_command(
        frequency=frequency,
        rtl_sdr_device=rtl_sdr_device,
        receiver_gain=receiver_gain,
        protocol_ids=normalized_protocol_ids,
        raw_rtl433_command=raw_rtl433_command,
    )
    return BridgeConfig(
        http_forward_enabled=http_forward_enabled,
        runtime_ingest_url=runtime_ingest_url,
        radio_band=normalize_radio_band(radio_band),
        frequency=frequency,
        rtl_sdr_device=normalize_auto_value(rtl_sdr_device),
        receiver_gain=normalize_auto_value(receiver_gain),
        protocol_ids=normalized_protocol_ids,
        raw_rtl433_command=raw_rtl433_command,
        rtl433_command=rtl433_command,
        forward_timeout_seconds=forward_timeout_seconds,
        retry_delay_seconds=retry_delay_seconds,
        startup_delay_seconds=startup_delay_seconds,
        extra_headers=merged_headers,
        mqtt_enabled=mqtt_enabled,
        mqtt_hostname=mqtt_hostname,
        mqtt_port=mqtt_port,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        mqtt_client_id=mqtt_client_id,
        mqtt_qos=mqtt_qos,
        mqtt_topic_root=mqtt_topic_root.rstrip("/"),
    )


def reconfigure_bridge_config(
    config: BridgeConfig,
    *,
    frequency: str | None = None,
    rtl_sdr_device: str | None = None,
    receiver_gain: str | None = None,
    protocol_ids_text: str | None = None,
) -> BridgeConfig:
    """Return a bridge config with discovery-time radio settings applied."""

    selected_band = config.radio_band
    selected_custom_frequency = config.frequency if config.radio_band == "custom" else ""
    if frequency is not None and frequency.strip():
        selected_band, selected_custom_frequency = parse_frequency_selection(frequency)

    return build_bridge_config(
        http_forward_enabled=config.http_forward_enabled,
        runtime_ingest_url=config.runtime_ingest_url,
        radio_band=selected_band,
        custom_frequency=selected_custom_frequency,
        rtl_sdr_device=rtl_sdr_device if rtl_sdr_device is not None else config.rtl_sdr_device,
        receiver_gain=receiver_gain if receiver_gain is not None else config.receiver_gain,
        protocol_ids_text=(
            protocol_ids_text
            if protocol_ids_text is not None
            else ",".join(config.protocol_ids)
        ),
        # A discovery-time radio choice is explicit and must not be shadowed by an
        # older advanced command override.
        rtl433_command_text="" if frequency is not None else (config.raw_rtl433_command or ""),
        forward_timeout_seconds=config.forward_timeout_seconds,
        retry_delay_seconds=config.retry_delay_seconds,
        startup_delay_seconds=config.startup_delay_seconds,
        extra_headers=config.extra_headers,
        mqtt_enabled=config.mqtt_enabled,
        mqtt_hostname=config.mqtt_hostname,
        mqtt_port=config.mqtt_port,
        mqtt_username=config.mqtt_username,
        mqtt_password=config.mqtt_password,
        mqtt_client_id=config.mqtt_client_id,
        mqtt_qos=config.mqtt_qos,
        mqtt_topic_root=config.mqtt_topic_root,
    )


def parse_frequency_selection(value: str) -> tuple[str, str]:
    """Accept a friendly band name or an rtl_433 custom frequency."""

    selected = str(value or "").strip()
    normalized = selected.lower().replace("_", "").replace("-", "")
    preset_aliases = {
        "315": "315mhz",
        "315m": "315mhz",
        "315mhz": "315mhz",
        "433": "433mhz",
        "433m": "433mhz",
        "433mhz": "433mhz",
        "43392": "433mhz",
        "43392m": "433mhz",
        "43392mhz": "433mhz",
        "868": "868mhz",
        "868m": "868mhz",
        "868mhz": "868mhz",
        "915": "915mhz",
        "915m": "915mhz",
        "915mhz": "915mhz",
    }
    preset = preset_aliases.get(normalized)
    if preset:
        return preset, ""
    if not selected:
        raise ValueError("Frequency cannot be blank.")
    return "custom", selected


def normalize_radio_band(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "").replace("-", "")
    if normalized in {"315", "315mhz", "315m"}:
        return "315mhz"
    if normalized in {"433", "433mhz", "43392", "43392mhz", "43392m"}:
        return "433mhz"
    if normalized in {"868", "868mhz", "868m"}:
        return "868mhz"
    if normalized in {"915", "915mhz", "915m"}:
        return "915mhz"
    if normalized in {"custom", "manual"}:
        return "custom"
    return DEFAULT_RADIO_BAND


def resolve_frequency(*, radio_band: str, custom_frequency: str = "") -> str:
    normalized_band = normalize_radio_band(radio_band)
    if normalized_band == "custom":
        frequency = str(custom_frequency or "").strip()
        if not frequency:
            raise ValueError("CUSTOM_FREQUENCY is required when RADIO_BAND is custom.")
        return frequency
    return RADIO_BAND_PRESETS[normalized_band]


def normalize_auto_value(value: str | int | float | None) -> str:
    normalized = str(value or "").strip()
    return normalized or "auto"


def parse_protocol_ids(raw_value: str) -> tuple[str, ...]:
    if not raw_value.strip():
        return ()
    return tuple(
        token.strip()
        for token in raw_value.replace(";", ",").split(",")
        if token.strip()
    )


def build_rtl433_command(
    *,
    frequency: str,
    rtl_sdr_device: str,
    receiver_gain: str,
    protocol_ids: tuple[str, ...],
    raw_rtl433_command: str | None = None,
) -> list[str]:
    if raw_rtl433_command:
        return shlex.split(raw_rtl433_command)

    command = ["rtl_433", "-F", "json", "-f", frequency]
    device = normalize_auto_value(rtl_sdr_device)
    gain = normalize_auto_value(receiver_gain)
    if device.lower() != "auto":
        command.extend(["-d", device])
    if gain.lower() != "auto":
        command.extend(["-g", gain])
    for protocol_id in protocol_ids:
        command.extend(["-R", protocol_id])
    return command


def parse_extra_headers(raw_value: str) -> dict[str, str]:
    raw_value = raw_value.strip()
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if key is not None and value is not None
    }


def build_packets_topic(topic_root: str) -> str:
    return f"{topic_root.rstrip('/')}/packets"


def build_model_packets_topic(topic_root: str, model: str) -> str:
    safe_model = str(model).strip().replace("/", "_").replace(" ", "_")
    return f"{topic_root.rstrip('/')}/models/{safe_model}/packets"


def build_packet_envelope(packet: dict[str, object]) -> dict[str, object]:
    return {
        "source": "rtl433",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "model": packet.get("model"),
        "device_hint": {
            "model": packet.get("model"),
            "id": _first_present(packet, ("id", "device_id", "device", "sid", "unit")),
            "channel": _first_present(packet, ("channel", "subtype")),
        },
        "packet": dict(packet),
    }


def _first_present(payload: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
