from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import logging
from typing import Any

import click
import httpx

from .bridge import Rtl433Bridge
from .config import (
    DEFAULT_RADIO_BAND,
    DEFAULT_MQTT_TOPIC_ROOT,
    DEFAULT_RTL433_COMMAND,
    DEFAULT_RUNTIME_INGEST_URL,
    BridgeConfig,
    build_bridge_config,
)

LOG_LEVEL_CHOICES = click.Choice(
    ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
    case_sensitive=False,
)
RADIO_BAND_CHOICES = click.Choice(
    ["315mhz", "433mhz", "868mhz", "915mhz", "custom"],
    case_sensitive=False,
)


def common_bridge_options(command):
    options = [
        click.option(
            "--http-forward-enabled/--no-http-forward-enabled",
            envvar="HTTP_FORWARD_ENABLED",
            default=True,
            show_default=True,
            help="Forward packets to the runtime ingest endpoint over HTTP.",
        ),
        click.option(
            "--runtime-ingest-url",
            envvar="RUNTIME_INGEST_URL",
            default=DEFAULT_RUNTIME_INGEST_URL,
            show_default=True,
            help="HTTP endpoint that accepts forwarded rtl_433 packets.",
        ),
        click.option(
            "--radio-band",
            envvar="RADIO_BAND",
            default=DEFAULT_RADIO_BAND,
            show_default=True,
            type=RADIO_BAND_CHOICES,
            help="Friendly radio band preset to listen on.",
        ),
        click.option(
            "--custom-frequency",
            envvar="CUSTOM_FREQUENCY",
            default="",
            help="Frequency to use when --radio-band custom is selected, for example 344.975M.",
        ),
        click.option(
            "--rtl-sdr-device",
            envvar="RTLSDR_DEVICE",
            default="auto",
            show_default=True,
            help="USB receiver to use. Leave as auto unless you have multiple SDR receivers.",
        ),
        click.option(
            "--receiver-gain",
            envvar="RECEIVER_GAIN",
            default="auto",
            show_default=True,
            help="Radio sensitivity. Leave as auto unless you are tuning reception.",
        ),
        click.option(
            "--rtl433-protocols",
            envvar="RTL433_PROTOCOLS",
            default="",
            help="Optional comma-separated rtl_433 protocol IDs to listen for. Leave blank for automatic decoding.",
        ),
        click.option(
            "--rtl433-command",
            envvar="RTL433_COMMAND",
            default=DEFAULT_RTL433_COMMAND,
            show_default=True,
            help="Advanced override: raw rtl_433 command string. If set, friendly radio options are ignored.",
        ),
        click.option(
            "--forward-timeout-seconds",
            envvar="FORWARD_TIMEOUT_SECONDS",
            default=10.0,
            show_default=True,
            type=float,
            help="HTTP timeout for forwarding one packet.",
        ),
        click.option(
            "--retry-delay-seconds",
            envvar="RETRY_DELAY_SECONDS",
            default=5.0,
            show_default=True,
            type=float,
            help="Delay before retrying runtime delivery or restarting rtl_433.",
        ),
        click.option(
            "--startup-delay-seconds",
            envvar="STARTUP_DELAY_SECONDS",
            default=2.0,
            show_default=True,
            type=float,
            help="Short delay before forwarding packets after rtl_433 starts.",
        ),
        click.option(
            "--extra-headers-json",
            envvar="BRIDGE_EXTRA_HEADERS_JSON",
            default="",
            show_default=False,
            help="Optional JSON object of extra HTTP headers to attach to forwarded packets.",
        ),
        click.option(
            "--mqtt-enabled/--no-mqtt-enabled",
            envvar="MQTT_ENABLED",
            default=False,
            show_default=True,
            help="Publish decoded packets to the shared MQTT source topics.",
        ),
        click.option(
            "--mqtt-hostname",
            envvar="MQTT_HOSTNAME",
            default="127.0.0.1",
            show_default=True,
            help="MQTT broker hostname.",
        ),
        click.option(
            "--mqtt-port",
            envvar="MQTT_PORT",
            default=1883,
            show_default=True,
            type=int,
            help="MQTT broker port.",
        ),
        click.option(
            "--mqtt-username",
            envvar="MQTT_USERNAME",
            default=None,
            help="Optional MQTT username.",
        ),
        click.option(
            "--mqtt-password",
            envvar="MQTT_PASSWORD",
            default=None,
            help="Optional MQTT password.",
        ),
        click.option(
            "--mqtt-client-id",
            envvar="MQTT_CLIENT_ID",
            default=None,
            help="Optional MQTT client identifier.",
        ),
        click.option(
            "--mqtt-qos",
            envvar="MQTT_QOS",
            default=0,
            show_default=True,
            type=int,
            help="MQTT QoS level for packet publishing.",
        ),
        click.option(
            "--mqtt-topic-root",
            envvar="MQTT_TOPIC_ROOT",
            default=DEFAULT_MQTT_TOPIC_ROOT,
            show_default=True,
            help="Shared source topic root used for rtl_433 packet publishing.",
        ),
        click.option(
            "--header",
            "header_pairs",
            multiple=True,
            help="Extra header in KEY=VALUE form. Can be passed multiple times.",
        ),
        click.option(
            "--log-level",
            envvar="LOG_LEVEL",
            default="INFO",
            show_default=True,
            type=LOG_LEVEL_CHOICES,
            help="Bridge log level.",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


try:
    BRIDGE_VERSION = package_version("piphi-rtl433-bridge")
except PackageNotFoundError:  # pragma: no cover - source checkout without an installed package
    BRIDGE_VERSION = "0.0.0"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=BRIDGE_VERSION, prog_name="piphi-rtl433-bridge")
def main() -> None:
    """Small rtl_433 helper for forwarding packets into a PiPhi runtime."""


@main.command("run")
@common_bridge_options
@click.option(
    "--dry-run/--no-dry-run",
    default=False,
    show_default=True,
    help="Print the resolved bridge config and exit without starting rtl_433.",
)
def run_command(
    http_forward_enabled: bool,
    runtime_ingest_url: str,
    radio_band: str,
    custom_frequency: str,
    rtl_sdr_device: str,
    receiver_gain: str,
    rtl433_protocols: str,
    rtl433_command: str,
    forward_timeout_seconds: float,
    retry_delay_seconds: float,
    startup_delay_seconds: float,
    extra_headers_json: str,
    mqtt_enabled: bool,
    mqtt_hostname: str,
    mqtt_port: int,
    mqtt_username: str | None,
    mqtt_password: str | None,
    mqtt_client_id: str | None,
    mqtt_qos: int,
    mqtt_topic_root: str,
    header_pairs: tuple[str, ...],
    log_level: str,
    dry_run: bool,
) -> None:
    _configure_logging(log_level)
    config = _build_config_from_inputs(
        http_forward_enabled=http_forward_enabled,
        runtime_ingest_url=runtime_ingest_url,
        radio_band=radio_band,
        custom_frequency=custom_frequency,
        rtl_sdr_device=rtl_sdr_device,
        receiver_gain=receiver_gain,
        rtl433_protocols=rtl433_protocols,
        rtl433_command=rtl433_command,
        forward_timeout_seconds=forward_timeout_seconds,
        retry_delay_seconds=retry_delay_seconds,
        startup_delay_seconds=startup_delay_seconds,
        extra_headers_json=extra_headers_json,
        mqtt_enabled=mqtt_enabled,
        mqtt_hostname=mqtt_hostname,
        mqtt_port=mqtt_port,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        mqtt_client_id=mqtt_client_id,
        mqtt_qos=mqtt_qos,
        mqtt_topic_root=mqtt_topic_root,
        header_pairs=header_pairs,
    )
    if dry_run:
        click.echo(json.dumps(_config_to_dict(config), indent=2, sort_keys=True))
        return

    bridge = Rtl433Bridge(config)
    asyncio.run(bridge.run_forever())


@main.command("print-config")
@common_bridge_options
def print_config_command(
    http_forward_enabled: bool,
    runtime_ingest_url: str,
    radio_band: str,
    custom_frequency: str,
    rtl_sdr_device: str,
    receiver_gain: str,
    rtl433_protocols: str,
    rtl433_command: str,
    forward_timeout_seconds: float,
    retry_delay_seconds: float,
    startup_delay_seconds: float,
    extra_headers_json: str,
    mqtt_enabled: bool,
    mqtt_hostname: str,
    mqtt_port: int,
    mqtt_username: str | None,
    mqtt_password: str | None,
    mqtt_client_id: str | None,
    mqtt_qos: int,
    mqtt_topic_root: str,
    header_pairs: tuple[str, ...],
    log_level: str,
) -> None:
    _configure_logging(log_level)
    config = _build_config_from_inputs(
        http_forward_enabled=http_forward_enabled,
        runtime_ingest_url=runtime_ingest_url,
        radio_band=radio_band,
        custom_frequency=custom_frequency,
        rtl_sdr_device=rtl_sdr_device,
        receiver_gain=receiver_gain,
        rtl433_protocols=rtl433_protocols,
        rtl433_command=rtl433_command,
        forward_timeout_seconds=forward_timeout_seconds,
        retry_delay_seconds=retry_delay_seconds,
        startup_delay_seconds=startup_delay_seconds,
        extra_headers_json=extra_headers_json,
        mqtt_enabled=mqtt_enabled,
        mqtt_hostname=mqtt_hostname,
        mqtt_port=mqtt_port,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        mqtt_client_id=mqtt_client_id,
        mqtt_qos=mqtt_qos,
        mqtt_topic_root=mqtt_topic_root,
        header_pairs=header_pairs,
    )
    click.echo(json.dumps(_config_to_dict(config), indent=2, sort_keys=True))


@main.command("ping-runtime")
@common_bridge_options
def ping_runtime_command(
    http_forward_enabled: bool,
    runtime_ingest_url: str,
    radio_band: str,
    custom_frequency: str,
    rtl_sdr_device: str,
    receiver_gain: str,
    rtl433_protocols: str,
    rtl433_command: str,
    forward_timeout_seconds: float,
    retry_delay_seconds: float,
    startup_delay_seconds: float,
    extra_headers_json: str,
    mqtt_enabled: bool,
    mqtt_hostname: str,
    mqtt_port: int,
    mqtt_username: str | None,
    mqtt_password: str | None,
    mqtt_client_id: str | None,
    mqtt_qos: int,
    mqtt_topic_root: str,
    header_pairs: tuple[str, ...],
    log_level: str,
) -> None:
    _configure_logging(log_level)
    config = _build_config_from_inputs(
        http_forward_enabled=http_forward_enabled,
        runtime_ingest_url=runtime_ingest_url,
        radio_band=radio_band,
        custom_frequency=custom_frequency,
        rtl_sdr_device=rtl_sdr_device,
        receiver_gain=receiver_gain,
        rtl433_protocols=rtl433_protocols,
        rtl433_command=rtl433_command,
        forward_timeout_seconds=forward_timeout_seconds,
        retry_delay_seconds=retry_delay_seconds,
        startup_delay_seconds=startup_delay_seconds,
        extra_headers_json=extra_headers_json,
        mqtt_enabled=mqtt_enabled,
        mqtt_hostname=mqtt_hostname,
        mqtt_port=mqtt_port,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        mqtt_client_id=mqtt_client_id,
        mqtt_qos=mqtt_qos,
        mqtt_topic_root=mqtt_topic_root,
        header_pairs=header_pairs,
    )
    result = asyncio.run(_ping_runtime(config))
    click.echo(json.dumps(result, indent=2, sort_keys=True))
    if result["reachable"] is not True:
        raise SystemExit(1)


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _build_config_from_inputs(
    *,
    http_forward_enabled: bool,
    runtime_ingest_url: str,
    radio_band: str,
    custom_frequency: str,
    rtl_sdr_device: str,
    receiver_gain: str,
    rtl433_protocols: str,
    rtl433_command: str,
    forward_timeout_seconds: float,
    retry_delay_seconds: float,
    startup_delay_seconds: float,
    extra_headers_json: str,
    mqtt_enabled: bool,
    mqtt_hostname: str,
    mqtt_port: int,
    mqtt_username: str | None,
    mqtt_password: str | None,
    mqtt_client_id: str | None,
    mqtt_qos: int,
    mqtt_topic_root: str,
    header_pairs: tuple[str, ...],
) -> BridgeConfig:
    extra_headers = _parse_header_pairs(header_pairs)
    _validate_extra_headers_json(extra_headers_json)
    return build_bridge_config(
        http_forward_enabled=http_forward_enabled,
        runtime_ingest_url=runtime_ingest_url,
        radio_band=radio_band,
        custom_frequency=custom_frequency,
        rtl_sdr_device=rtl_sdr_device,
        receiver_gain=receiver_gain,
        protocol_ids_text=rtl433_protocols,
        rtl433_command_text=rtl433_command,
        forward_timeout_seconds=forward_timeout_seconds,
        retry_delay_seconds=retry_delay_seconds,
        startup_delay_seconds=startup_delay_seconds,
        extra_headers_json=extra_headers_json,
        extra_headers=extra_headers,
        mqtt_enabled=mqtt_enabled,
        mqtt_hostname=mqtt_hostname,
        mqtt_port=mqtt_port,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        mqtt_client_id=mqtt_client_id,
        mqtt_qos=mqtt_qos,
        mqtt_topic_root=mqtt_topic_root,
    )


def _parse_header_pairs(header_pairs: tuple[str, ...]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pair in header_pairs:
        if "=" not in pair:
            raise click.BadParameter(
                f"Header '{pair}' is not in KEY=VALUE format.",
                param_hint="--header",
            )
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise click.BadParameter(
                f"Header '{pair}' is missing a key.",
                param_hint="--header",
            )
        parsed[key] = value
    return parsed


def _validate_extra_headers_json(raw_value: str) -> None:
    if not raw_value.strip():
        return
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(
            f"Invalid JSON for --extra-headers-json: {exc.msg}",
            param_hint="--extra-headers-json",
        ) from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter(
            "--extra-headers-json must be a JSON object.",
            param_hint="--extra-headers-json",
        )


def _config_to_dict(config: BridgeConfig) -> dict[str, Any]:
    return {
        "http_forward_enabled": config.http_forward_enabled,
        "runtime_ingest_url": config.runtime_ingest_url,
        "radio_band": config.radio_band,
        "frequency": config.frequency,
        "rtl_sdr_device": config.rtl_sdr_device,
        "receiver_gain": config.receiver_gain,
        "protocol_ids": list(config.protocol_ids),
        "raw_rtl433_command": config.raw_rtl433_command,
        "rtl433_command": config.rtl433_command,
        "forward_timeout_seconds": config.forward_timeout_seconds,
        "retry_delay_seconds": config.retry_delay_seconds,
        "startup_delay_seconds": config.startup_delay_seconds,
        "extra_headers": config.extra_headers,
        "mqtt_enabled": config.mqtt_enabled,
        "mqtt_hostname": config.mqtt_hostname,
        "mqtt_port": config.mqtt_port,
        "mqtt_client_id": config.mqtt_client_id,
        "mqtt_qos": config.mqtt_qos,
        "mqtt_topic_root": config.mqtt_topic_root,
    }


async def _ping_runtime(config: BridgeConfig) -> dict[str, Any]:
    if not config.http_forward_enabled:
        return {
            "reachable": False,
            "error": "HTTP forwarding is disabled for this bridge config.",
            "runtime_ingest_url": config.runtime_ingest_url,
        }
    try:
        async with httpx.AsyncClient(timeout=config.forward_timeout_seconds) as client:
            response = await client.get(
                config.runtime_ingest_url,
                headers=config.extra_headers,
            )
        return {
            "reachable": True,
            "status_code": response.status_code,
            "runtime_ingest_url": config.runtime_ingest_url,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "error": str(exc),
            "runtime_ingest_url": config.runtime_ingest_url,
        }
