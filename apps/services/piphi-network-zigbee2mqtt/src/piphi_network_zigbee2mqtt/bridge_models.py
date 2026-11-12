from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


AdapterTransport = Literal["serial", "tcp", "socket"]
AdapterRuntime = Literal["docker", "native"]
SupervisorMode = Literal["docker", "pm2"]
SupervisorAction = Literal["status", "start", "stop", "restart", "logs"]
RestartPolicy = Literal["never", "changed", "always"]


class AdapterCandidate(BaseModel):
    id: str
    path: str
    display_name: str
    transport: AdapterTransport = "serial"
    adapter_hint: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    stable: bool = False
    source: str
    manufacturer: str | None = None
    product: str | None = None
    serial_number: str | None = None
    vid: int | None = None
    pid: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MqttSettings(BaseModel):
    server: str = "mqtt://127.0.0.1:1883"
    user: str | None = None
    password: str | None = None
    base_topic: str = "zigbee2mqtt"

    @field_validator("base_topic")
    @classmethod
    def normalize_base_topic(cls, value: str) -> str:
        token = str(value or "").strip().strip("/")
        if not token:
            raise ValueError("MQTT base_topic is required.")
        return token


class SerialSettings(BaseModel):
    port: str
    adapter: str | None = None
    baudrate: int | None = None
    disable_led: bool | None = None

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("serial.port is required.")
        return token


class AdvancedNetworkSettings(BaseModel):
    pan_id: int | None = Field(default=None, ge=0, le=65535)
    ext_pan_id: list[int] | None = None
    channel: int | None = Field(default=None, ge=11, le=26)
    network_key: list[int] | Literal["GENERATE"] | None = None


class Zigbee2MqttBridgeConfig(BaseModel):
    mqtt: MqttSettings = Field(default_factory=MqttSettings)
    serial: SerialSettings
    frontend_enabled: bool = True
    frontend_port: int = Field(default=8080, ge=1, le=65535)
    permit_join: bool = False
    homeassistant: bool = False
    availability: bool = True
    advanced: AdvancedNetworkSettings = Field(default_factory=AdvancedNetworkSettings)
    data_path: str = "/app/data"
    runtime: AdapterRuntime = "docker"


class RenderedBridgeConfig(BaseModel):
    yaml: str
    data_path: str
    config_path: str | None = None
    runtime: AdapterRuntime
    rendered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config_hash: str | None = None


class WriteConfigRequest(BaseModel):
    config: Zigbee2MqttBridgeConfig
    config_path: str | None = None


class ConfigWriteResult(BaseModel):
    config_path: str
    config_hash: str
    previous_hash: str | None = None
    changed: bool
    backup_path: str | None = None
    written_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BridgeSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    service: str = "zigbee2mqtt-sidecar"
    configured: bool
    config_path: str | None = None
    data_path: str | None = None
    runtime: AdapterRuntime | None = None
    adapter_path: str | None = None
    adapter_hint: str | None = None
    mqtt_server: str | None = None
    mqtt_base_topic: str | None = None
    last_rendered_at: datetime | None = None
    config_hash: str | None = None
    last_error: str | None = None
    supervisor: dict[str, Any] | None = None
    mqtt_check: dict[str, Any] | None = None

    @field_serializer("mqtt_server")
    def serialize_mqtt_server(self, value: str | None) -> str | None:
        return redact_mqtt_server(value)


class CommandResult(BaseModel):
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class DockerSupervisorSettings(BaseModel):
    image: str = "ghcr.io/koenkk/zigbee2mqtt:latest"
    container_name: str = "piphi-zigbee2mqtt"
    host_data_path: str
    container_data_path: str = "/app/data"
    device_path: str | None = None
    frontend_port: int | None = Field(default=8080, ge=1, le=65535)
    network_mode: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class Pm2SupervisorSettings(BaseModel):
    process_name: str = "piphi-zigbee2mqtt"
    working_dir: str
    script: str = "index.js"
    interpreter: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class SupervisorRequest(BaseModel):
    mode: SupervisorMode
    docker: DockerSupervisorSettings | None = None
    pm2: Pm2SupervisorSettings | None = None
    dry_run: bool = False


class SupervisorLogsRequest(SupervisorRequest):
    tail: int = Field(default=100, ge=1, le=2000)


class SupervisorResponse(BaseModel):
    ok: bool
    mode: SupervisorMode
    action: SupervisorAction
    status: str
    commands: list[list[str]] = Field(default_factory=list)
    results: list[CommandResult] = Field(default_factory=list)
    message: str | None = None


class PrerequisiteCheckRequest(BaseModel):
    mode: SupervisorMode
    docker: DockerSupervisorSettings | None = None
    pm2: Pm2SupervisorSettings | None = None
    dry_run: bool = False


class PrerequisiteCheckResponse(BaseModel):
    ok: bool
    mode: SupervisorMode
    checks: list[dict[str, Any]] = Field(default_factory=list)
    message: str | None = None


class MqttCheckRequest(BaseModel):
    server: str | None = None
    timeout_seconds: float = Field(default=3.0, ge=0.1, le=30.0)
    dry_run: bool = False


class MqttCheckResponse(BaseModel):
    ok: bool
    server: str
    host: str
    port: int
    status: str
    message: str | None = None

    @field_serializer("server")
    def serialize_server(self, value: str) -> str:
        return redact_mqtt_server(value) or ""


class Zigbee2MqttApiRequest(BaseModel):
    server: str | None = None
    base_topic: str | None = None
    timeout_seconds: float = Field(default=8.0, ge=0.5, le=60.0)
    dry_run: bool = False

    @field_validator("base_topic")
    @classmethod
    def normalize_base_topic(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value or "").strip().strip("/")
        if not token:
            raise ValueError("base_topic cannot be blank.")
        return token


class Zigbee2MqttDevice(BaseModel):
    model_config = ConfigDict(extra="allow")

    friendly_name: str
    ieee_address: str | None = None
    type: str | None = None
    interview_state: str | None = None
    # Deprecated fields remain input-compatible with older retained payloads.
    interview_completed: bool | None = None
    interviewing: bool | None = None
    supported: bool | None = None
    definition: dict[str, Any] | None = None
    power_source: str | None = None
    date_code: str | None = None
    import_eligible: bool = True
    import_blocked_reason: str | None = None

    @model_validator(mode="after")
    def derive_import_eligibility(self) -> "Zigbee2MqttDevice":
        state = str(self.interview_state or "").strip().lower()
        device_type = str(self.type or "").strip().lower()
        if device_type == "coordinator":
            self.import_eligible = False
            self.import_blocked_reason = "coordinator"
        elif self.supported is False:
            self.import_eligible = False
            self.import_blocked_reason = "unsupported"
        elif state in {"failed", "interview_failed"}:
            self.import_eligible = False
            self.import_blocked_reason = "interview_failed"
        elif state in {"pending", "started", "interviewing"}:
            self.import_eligible = False
            self.import_blocked_reason = "interview_in_progress"
        return self


class DeviceListRequest(Zigbee2MqttApiRequest):
    pass


class DeviceListResponse(BaseModel):
    ok: bool
    status: str
    devices: list[Zigbee2MqttDevice] = Field(default_factory=list)
    server: str
    base_topic: str
    request_topic: str | None = None
    response_topic: str
    transaction: str | None = None
    message: str | None = None
    raw: Any | None = None

    @field_serializer("server")
    def serialize_server(self, value: str) -> str:
        return redact_mqtt_server(value) or ""


class NetworkMapNode(BaseModel):
    id: str
    friendly_name: str
    type: str
    ieee_address: str | None = None
    network_address: int | None = None
    manufacturer: str | None = None
    model: str | None = None


class NetworkMapLink(BaseModel):
    source: str
    target: str
    link_quality: int | None = Field(default=None, ge=0, le=255)
    depth: int | None = Field(default=None, ge=0)
    routes: list[int] = Field(default_factory=list)


class NetworkMapRequest(Zigbee2MqttApiRequest):
    routes: bool = False


class NetworkMapResponse(BaseModel):
    ok: bool
    status: str
    nodes: list[NetworkMapNode] = Field(default_factory=list)
    links: list[NetworkMapLink] = Field(default_factory=list)
    routes_included: bool = False
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    server: str
    base_topic: str
    request_topic: str
    response_topic: str
    transaction: str | None = None
    message: str | None = None

    @field_serializer("server")
    def serialize_server(self, value: str) -> str:
        return redact_mqtt_server(value) or ""


class PermitJoinRequest(Zigbee2MqttApiRequest):
    value: bool = True
    time: int = Field(default=60, ge=1, le=254)
    device: str | None = None


class PermitJoinResponse(BaseModel):
    ok: bool
    status: str
    value: bool
    time: int
    device: str | None = None
    server: str
    base_topic: str
    request_topic: str
    response_topic: str
    transaction: str | None = None
    message: str | None = None
    raw: Any | None = None

    @field_serializer("server")
    def serialize_server(self, value: str) -> str:
        return redact_mqtt_server(value) or ""


class ApplyBridgeRequest(WriteConfigRequest):
    supervisor: SupervisorRequest | None = None
    restart_policy: RestartPolicy = "changed"
    mqtt_check: MqttCheckRequest | None = Field(default_factory=MqttCheckRequest)


class ApplyBridgeResponse(BaseModel):
    ok: bool
    rendered: RenderedBridgeConfig
    write: ConfigWriteResult
    restart_required: bool
    supervisor: SupervisorResponse | None = None
    mqtt_check: MqttCheckResponse | None = None
    message: str | None = None


class SidecarStore:
    def __init__(self) -> None:
        self.current_config: Zigbee2MqttBridgeConfig | None = None
        self.current_render: RenderedBridgeConfig | None = None
        self.config_path: str | None = None
        self.config_hash: str | None = None
        self.last_error: str | None = None
        self.last_supervisor: SupervisorResponse | None = None
        self.last_mqtt_check: MqttCheckResponse | None = None
        self.last_devices: DeviceListResponse | None = None
        self.last_network_map: NetworkMapResponse | None = None
        self.last_permit_join: PermitJoinResponse | None = None

    def snapshot(self) -> BridgeSnapshot:
        config = self.current_config
        render = self.current_render
        return BridgeSnapshot(
            configured=config is not None,
            config_path=self.config_path,
            data_path=config.data_path if config else None,
            runtime=config.runtime if config else None,
            adapter_path=config.serial.port if config else None,
            adapter_hint=config.serial.adapter if config else None,
            mqtt_server=config.mqtt.server if config else None,
            mqtt_base_topic=config.mqtt.base_topic if config else None,
            last_rendered_at=render.rendered_at if render else None,
            config_hash=self.config_hash,
            last_error=self.last_error,
            supervisor=self.last_supervisor.model_dump(mode="json") if self.last_supervisor else None,
            mqtt_check=self.last_mqtt_check.model_dump(mode="json") if self.last_mqtt_check else None,
            devices=self.last_devices.model_dump(mode="json") if self.last_devices else None,
            network_map=self.last_network_map.model_dump(mode="json") if self.last_network_map else None,
            permit_join=self.last_permit_join.model_dump(mode="json") if self.last_permit_join else None,
        )


def ensure_parent_directory(path: str) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def redact_mqtt_server(value: str | None) -> str | None:
    """Return a browser-safe MQTT endpoint with user-info removed."""
    token = str(value or "").strip()
    if not token:
        return None
    has_scheme = "://" in token
    parsed = urlsplit(token if has_scheme else f"mqtt://{token}")
    host = parsed.hostname
    if not host:
        return token.split("@", 1)[-1]
    host_token = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = f"{host_token}:{parsed.port}" if parsed.port else host_token
    redacted = urlunsplit((parsed.scheme or "mqtt", netloc, parsed.path, parsed.query, parsed.fragment))
    return redacted if has_scheme else redacted.split("://", 1)[-1]
