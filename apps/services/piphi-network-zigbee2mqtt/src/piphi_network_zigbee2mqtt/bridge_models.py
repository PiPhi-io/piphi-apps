from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .settings import DEFAULT_ZIGBEE2MQTT_IMAGE
from .stopped_coordinator_evidence import StoppedCoordinatorEvidence

AdapterTransport = Literal["serial", "tcp", "socket"]
AdapterRuntime = Literal["docker", "native"]
SupervisorMode = Literal["docker", "pm2"]
SupervisorAction = Literal["status", "start", "stop", "restart", "logs"]
RestartPolicy = Literal["never", "changed", "always"]
NetworkFormationMode = Literal["reuse_existing", "form_new"]
NetworkByte = Annotated[int, Field(strict=True, ge=0, le=255)]
NetworkByteList = Annotated[list[NetworkByte], Field(min_length=16, max_length=16)]
ExtendedPanId = Annotated[list[NetworkByte], Field(min_length=8, max_length=8)]


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
    ca: str | None = None
    cert: str | None = None
    key: str | None = None
    reject_unauthorized: bool = True

    @field_validator("base_topic")
    @classmethod
    def normalize_base_topic(cls, value: str) -> str:
        token = str(value or "").strip().strip("/")
        if not token:
            raise ValueError("MQTT base_topic is required.")
        return token

    @model_validator(mode="after")
    def validate_tls(self) -> MqttSettings:
        if bool(self.cert) != bool(self.key):
            raise ValueError("MQTT client cert and key must be configured together.")
        if not self.reject_unauthorized:
            raise ValueError("MQTT certificate verification cannot be disabled.")
        for value in (self.ca, self.cert, self.key):
            if value and (not Path(value).is_absolute() or ".." in Path(value).parts):
                raise ValueError("MQTT trust files must use absolute mounted paths.")
        return self


class MqttMessagesRequest(BaseModel):
    topics: list[str] = Field(min_length=1, max_length=256)
    after_sequence: int = Field(default=0, ge=0)


class MqttPublishRequest(BaseModel):
    topic: str
    payload: dict[str, Any]
    dry_run: bool = False


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
    ext_pan_id: ExtendedPanId | None = None
    channel: int | None = Field(default=None, ge=11, le=26)
    network_key: NetworkByteList | Literal["GENERATE"] | None = None

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
    rendered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    config_hash: str | None = None

    @field_serializer("yaml")
    def serialize_yaml(self, value: str) -> str:
        return redact_rendered_yaml(value)


class WriteConfigRequest(BaseModel):
    config: Zigbee2MqttBridgeConfig
    config_path: str | None = None
    network_formation: NetworkFormationMode = "reuse_existing"
    confirm_form_new: bool = False
    backup_path: str | None = None
    backup_sha256: str | None = None
    acknowledge_network_change_warning: bool = False
    confirm_network_change: bool = False
    coordinator_stop_authority: Literal["local", "core_managed_helper"] = "local"
    stopped_coordinator_evidence: StoppedCoordinatorEvidence | None = None

    @model_validator(mode="after")
    def validate_network_formation(self) -> WriteConfigRequest:
        if self.network_formation == "form_new" and not self.confirm_form_new:
            raise ValueError("Forming a new Zigbee network requires explicit confirmation.")
        if self.config.advanced.network_key == "GENERATE" and self.network_formation != "form_new":
            raise ValueError("GENERATE is only allowed when forming a new Zigbee network.")
        return self


class WriteBridgeRequest(WriteConfigRequest):
    coordinator_identity: str = Field(min_length=1, max_length=256)


class ConfigWriteResult(BaseModel):
    config_path: str
    config_hash: str
    previous_hash: str | None = None
    changed: bool
    backup_path: str | None = None
    written_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NetworkBackupRequest(BaseModel):
    data_path: str
    adapter_family: str = Field(min_length=1, max_length=64)
    zigbee2mqtt_version: str = Field(min_length=1, max_length=64)
    adapter_backup_supported: bool = False
    coordinator_identity: str = Field(min_length=1, max_length=256)
    coordinator_port: str = Field(min_length=1, max_length=512)
    coordinator_stop_authority: Literal["local", "core_managed_helper"] = "local"
    stopped_coordinator_evidence: StoppedCoordinatorEvidence | None = None

    @model_validator(mode="after")
    def require_managed_stop_evidence(self) -> NetworkBackupRequest:
        if (
            self.coordinator_stop_authority == "core_managed_helper"
            and self.stopped_coordinator_evidence is None
        ):
            raise ValueError("Core-managed backup requires stopped-coordinator evidence.")
        return self


class NetworkBackupResponse(BaseModel):
    backup_path: str
    backup_sha256: str
    files: list[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    adapter_family: str
    zigbee2mqtt_version: str
    coordinator_backup_created_at: datetime | None = None
    recoverable: bool


class NetworkRestoreRequest(BaseModel):
    data_path: str
    backup_path: str
    backup_sha256: str
    adapter_family: str = Field(min_length=1, max_length=64)
    coordinator_identity: str = Field(min_length=1, max_length=256)
    coordinator_port: str
    confirm_restore: bool = False
    coordinator_stop_authority: Literal["local", "core_managed_helper"] = "local"
    stopped_coordinator_evidence: StoppedCoordinatorEvidence | None = None

    @model_validator(mode="after")
    def require_managed_stop_evidence(self) -> NetworkRestoreRequest:
        if (
            self.coordinator_stop_authority == "core_managed_helper"
            and self.stopped_coordinator_evidence is None
        ):
            raise ValueError("Core-managed restore requires stopped-coordinator evidence.")
        return self


class NetworkRestoreResponse(BaseModel):
    restored: bool
    files: list[str]
    rollback_backup: NetworkBackupResponse
    message: str
    verification_status: Literal["pending", "passed"]


class EncryptedBackupExportRequest(BaseModel):
    backup_path: str
    backup_sha256: str
    passphrase: str = Field(min_length=12, max_length=1024, repr=False)


class EncryptedBackupExportResponse(BaseModel):
    export_path: str
    export_sha256: str
    format: Literal["piphi-zigbee-aes256-gcm-v1"] = "piphi-zigbee-aes256-gcm-v1"


class EncryptedBackupImportRequest(BaseModel):
    data_path: str
    export_path: str
    export_sha256: str
    passphrase: str = Field(min_length=12, max_length=1024, repr=False)


class CoordinatorMigrationPlanRequest(BaseModel):
    data_path: str
    backup_path: str
    backup_sha256: str
    source_adapter_family: str = Field(min_length=1, max_length=64)
    target_adapter_family: str = Field(min_length=1, max_length=64)
    target_coordinator_identity: str = Field(min_length=1, max_length=256)
    target_coordinator_port: str = Field(min_length=1, max_length=512)
    target_adapter: str | None = Field(default=None, min_length=1, max_length=64)
    compatibility_record_id: str = Field(min_length=1, max_length=128)
    compatibility_evidence: str | None = Field(default=None, min_length=1, max_length=512)
    coordinator_stop_authority: Literal["local", "core_managed_helper"] = "local"
    stopped_coordinator_evidence: StoppedCoordinatorEvidence | None = None

    @field_validator("source_adapter_family", "target_adapter_family")
    @classmethod
    def normalize_adapter_family(cls, value: str) -> str:
        token = value.strip().lower()
        if not token:
            raise ValueError("Adapter family is required.")
        return token

    @model_validator(mode="after")
    def require_managed_stop_evidence(self) -> CoordinatorMigrationPlanRequest:
        if (
            self.coordinator_stop_authority == "core_managed_helper"
            and self.stopped_coordinator_evidence is None
        ):
            raise ValueError("Core-managed migration requires stopped-coordinator evidence.")
        return self


class CoordinatorMigrationPlanResponse(BaseModel):
    plan_id: str
    compatible: bool
    target_available: bool
    source_adapter_family: str
    target_adapter_family: str
    target_coordinator_identity: str
    target_coordinator_port: str
    compatibility_basis: Literal["governed_same_family_record"]
    compatibility_record_id: str
    steps: list[str]
    warnings: list[str] = Field(default_factory=list)


class CoordinatorMigrationApplyRequest(CoordinatorMigrationPlanRequest):
    plan_id: str = Field(pattern=r"sha256:[0-9a-f]{64}")
    confirm_migration: bool = False


class CoordinatorMigrationApplyResponse(BaseModel):
    migrated: bool
    plan_id: str
    target_coordinator_identity: str
    target_coordinator_port: str
    restored_files: list[str]
    rollback_backup: NetworkBackupResponse
    message: str


class CoordinatorProbeRequest(BaseModel):
    port: str


class CoordinatorProbeResponse(BaseModel):
    available: bool
    in_use: bool
    method: str
    exclusive_verified: bool
    holders: list[str] = Field(default_factory=list)
    message: str | None = None


class CoordinatorClaimRepairRequest(BaseModel):
    coordinator_identity: str = Field(min_length=1, max_length=256)
    coordinator_port: str = Field(min_length=1, max_length=512)
    expected_generation: int = Field(ge=1)
    confirm_stale_repair: bool = False
    coordinator_stop_authority: Literal["local", "core_managed_helper"] = "local"
    stopped_coordinator_evidence: StoppedCoordinatorEvidence | None = None

    @model_validator(mode="after")
    def require_managed_stop_evidence(self) -> CoordinatorClaimRepairRequest:
        if (
            self.coordinator_stop_authority == "core_managed_helper"
            and self.stopped_coordinator_evidence is None
        ):
            raise ValueError("Core-managed stale-claim repair requires stopped-coordinator evidence.")
        return self


class CoordinatorClaimResponse(BaseModel):
    coordinator_identity: str
    owner_id: str
    generation: int
    lease_expires_at: datetime


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
    coordinator_claimed: bool = False
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
    image: str = DEFAULT_ZIGBEE2MQTT_IMAGE
    container_name: str = "piphi-zigbee2mqtt"
    host_data_path: str
    container_data_path: str = "/app/data"
    device_path: str | None = None
    frontend_port: int | None = Field(default=8080, ge=1, le=65535)
    network_mode: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def restrict_runtime_options(self) -> DockerSupervisorSettings:
        if self.image != DEFAULT_ZIGBEE2MQTT_IMAGE:
            raise ValueError("docker.image is managed by PiPhi and cannot be overridden.")
        if self.container_name != "piphi-zigbee2mqtt":
            raise ValueError("docker.container_name is managed by PiPhi and cannot be overridden.")
        if self.container_data_path != "/app/data":
            raise ValueError("docker.container_data_path is managed by PiPhi and cannot be overridden.")
        if self.network_mode not in {None, "bridge"}:
            raise ValueError("docker.network_mode must use the isolated bridge network.")
        if set(self.environment) - {"TZ"}:
            raise ValueError("docker.environment only permits the TZ setting.")
        if Path(self.host_data_path).expanduser().resolve() != Path(
            "/var/lib/piphi/zigbee2mqtt"
        ).resolve():
            raise ValueError("docker.host_data_path must use the managed Zigbee2MQTT data directory.")
        if self.device_path and not self.device_path.startswith(
            ("/dev/serial/by-id/", "/dev/serial/by-path/", "/dev/tty")
        ):
            raise ValueError("docker.device_path must be a supported coordinator device path.")
        if self.device_path and ".." in Path(self.device_path).parts:
            raise ValueError("docker.device_path cannot contain path traversal.")
        return self


class Pm2SupervisorSettings(BaseModel):
    process_name: str = "piphi-zigbee2mqtt"
    working_dir: str
    script: str = "index.js"
    interpreter: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def restrict_runtime_options(self) -> Pm2SupervisorSettings:
        if self.process_name != "piphi-zigbee2mqtt":
            raise ValueError("pm2.process_name is managed by PiPhi and cannot be overridden.")
        if self.script != "index.js" or self.interpreter is not None:
            raise ValueError("pm2 script and interpreter are managed by PiPhi.")
        if set(self.env) - {"ZIGBEE2MQTT_DATA"}:
            raise ValueError("pm2.env only permits ZIGBEE2MQTT_DATA.")
        if self.env.get("ZIGBEE2MQTT_DATA") not in {None, "/var/lib/piphi/zigbee2mqtt"}:
            raise ValueError("pm2 ZIGBEE2MQTT_DATA must use the managed data directory.")
        if Path(self.working_dir).expanduser().resolve() != Path("/opt/zigbee2mqtt").resolve():
            raise ValueError("pm2.working_dir must use the managed Zigbee2MQTT installation.")
        return self


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
    def derive_import_eligibility(self) -> Zigbee2MqttDevice:
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
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
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
    operation_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    confirmation: Literal["open-zigbee-network", "close-zigbee-network"]

    @model_validator(mode="after")
    def validate_confirmation(self) -> PermitJoinRequest:
        expected = "open-zigbee-network" if self.value else "close-zigbee-network"
        if self.confirmation != expected:
            raise ValueError(f"Permit join requires confirmation={expected}.")
        allowed = {
            item.strip()
            for item in os.getenv("PIPHI_PERMIT_JOIN_DEVICE_ALLOWLIST", "coordinator").split(",")
            if item.strip()
        }
        if self.device and self.device not in allowed:
            raise ValueError("Permit join target is not allow-listed.")
        return self


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


class ApplyBridgeRequest(WriteBridgeRequest):
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
    rolled_back: bool = False


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
        self.coordinator_identity: str | None = None
        self.coordinator_owner_id: str | None = None
        self.coordinator_claim_generation: int | None = None

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
            coordinator_claimed=self.coordinator_identity is not None,
            last_rendered_at=render.rendered_at if render else None,
            config_hash=self.config_hash,
            last_error=self.last_error,
            supervisor=self.last_supervisor.model_dump(mode="json") if self.last_supervisor else None,
            mqtt_check=self.last_mqtt_check.model_dump(mode="json") if self.last_mqtt_check else None,
            devices=self.last_devices.model_dump(mode="json") if self.last_devices else None,
            network_map=self.last_network_map.model_dump(mode="json") if self.last_network_map else None,
            permit_join=self.last_permit_join.model_dump(mode="json") if self.last_permit_join else None,
        )


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


def redact_rendered_yaml(value: str) -> str:
    lines: list[str] = []
    redact_network_key = False
    network_key_indent = 0
    for line in value.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if redact_network_key and stripped.startswith("-") and indent > network_key_indent:
            continue
        redact_network_key = False
        if stripped.startswith("password:"):
            lines.append(f'{line[:indent]}password: "[redacted]"')
        elif stripped.startswith("network_key:"):
            lines.append(f'{line[:indent]}network_key: "[redacted]"')
            redact_network_key = True
            network_key_indent = indent
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if value.endswith("\n") else "")
