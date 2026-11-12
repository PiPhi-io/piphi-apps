from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

from .bridge_models import MqttSettings, RenderedBridgeConfig, Zigbee2MqttBridgeConfig
from .config_store import text_sha256


def render_zigbee2mqtt_config(config: Zigbee2MqttBridgeConfig) -> RenderedBridgeConfig:
    payload: dict[str, Any] = {
        "homeassistant": config.homeassistant,
        "permit_join": config.permit_join,
        "mqtt": _render_mqtt_settings(config.mqtt),
        "serial": {
            "port": config.serial.port,
        },
        "frontend": {
            "enabled": config.frontend_enabled,
            "port": config.frontend_port,
        },
        "availability": config.availability,
    }
    if config.serial.adapter:
        payload["serial"]["adapter"] = config.serial.adapter
    if config.serial.baudrate:
        payload["serial"]["baudrate"] = config.serial.baudrate
    if config.serial.disable_led is not None:
        payload["serial"]["disable_led"] = config.serial.disable_led

    advanced = config.advanced.model_dump(exclude_none=True)
    if advanced:
        payload["advanced"] = advanced

    yaml = _render_yaml(payload)
    return RenderedBridgeConfig(
        yaml=yaml,
        data_path=config.data_path,
        runtime=config.runtime,
        config_hash=text_sha256(yaml),
    )


def _render_mqtt_settings(settings: MqttSettings) -> dict[str, Any]:
    server, url_user, url_password = _split_mqtt_server_credentials(settings.server)
    payload: dict[str, Any] = {
        "base_topic": settings.base_topic,
        "server": server,
    }
    user = settings.user or url_user
    password = settings.password or url_password
    if user:
        payload["user"] = user
    if password:
        payload["password"] = password
    return payload


def _split_mqtt_server_credentials(server: str) -> tuple[str, str | None, str | None]:
    text = str(server or "").strip()
    parsed = urlparse(text if "://" in text else f"mqtt://{text}")
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    if not username and not password:
        return text, None, None

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port else host
    clean_server = urlunparse(
        (
            parsed.scheme or "mqtt",
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return clean_server, username, password


def _render_yaml(value: Any, indent: int = 0) -> str:
    lines = _render_yaml_lines(value, indent)
    return "\n".join(lines) + "\n"


def _render_yaml_lines(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, dict):
                lines.append(f"{prefix}{key}:")
                lines.extend(_render_yaml_lines(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}{key}:")
                lines.extend(_render_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.extend(_render_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return lines
    return [f"{prefix}{_format_scalar(value)}"]


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "GENERATE":
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
