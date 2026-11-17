from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .bridge_models import MqttSettings, SerialSettings, SidecarStore, Zigbee2MqttBridgeConfig
from .config_renderer import render_zigbee2mqtt_config
from .config_store import write_config_atomic
from .contract import CAPABILITIES, COMMANDS
from .coordinator_claims import (
    CoordinatorClaimConflict,
    claim_owner_id,
    claim_store,
    stable_coordinator_identity,
)
from .coordinator_probe import probe_coordinator
from .mqtt_gateway import mqtt_gateway
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .stopped_coordinator_evidence import verify_stopped_coordinator_evidence

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
config_sync = starter.config_sync

capabilities = CAPABILITIES
commands = COMMANDS
sidecar_store = SidecarStore()


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "config": config.model_dump(exclude={"mqtt_password"}),
    }


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity="info",
    )
    registry.append_event(event)
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    if config.serial_port:
        if not config.coordinator_identity:
            raise HTTPException(status_code=400, detail="A stable coordinator_identity is required.")
        selected_coordinator_identity = config.coordinator_identity.strip()
        coordinator_identity = stable_coordinator_identity(selected_coordinator_identity)
        owner_id = claim_owner_id()
        previous_identity = sidecar_store.coordinator_identity
        previous_owner_id = sidecar_store.coordinator_owner_id
        previous_generation = sidecar_store.coordinator_claim_generation
        if config.coordinator_stop_authority == "core_managed_helper":
            evidence = config.stopped_coordinator_evidence
            if evidence is None:
                raise HTTPException(
                    status_code=409,
                    detail="Core-managed config sync is missing stopped-coordinator evidence.",
                )
            try:
                verify_stopped_coordinator_evidence(
                    evidence,
                    operation="config_sync",
                    coordinator_identity=selected_coordinator_identity,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif sidecar_store.coordinator_identity != coordinator_identity:
            probe = probe_coordinator(config.serial_port)
            if not probe.available:
                raise HTTPException(
                    status_code=409,
                    detail=probe.message or "Coordinator is unavailable or already in use.",
                )
        try:
            claim = claim_store.claim(
                coordinator_identity,
                owner_id,
                expected_generation=(
                    previous_generation
                    if previous_identity == coordinator_identity and previous_owner_id == owner_id
                    else None
                ),
            )
        except CoordinatorClaimConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        mqtt_base_topic = config.mqtt_base_topic.strip().strip("/")
        topic_prefix = str(config.mqtt_topic_prefix or "").strip().strip("/")
        if topic_prefix and not mqtt_base_topic.startswith(f"{topic_prefix}/"):
            mqtt_base_topic = f"{topic_prefix}/{mqtt_base_topic}"
        bridge_config = Zigbee2MqttBridgeConfig(
            mqtt=MqttSettings(
                server=config.mqtt_server,
                user=config.mqtt_username,
                password=config.mqtt_password,
                base_topic=mqtt_base_topic,
            ),
            serial=SerialSettings(port=config.serial_port, adapter=config.adapter),
            data_path=config.data_path,
        )
        rendered = render_zigbee2mqtt_config(bridge_config)
        target_path = f"{bridge_config.data_path.rstrip('/')}/configuration.yaml"
        try:
            write_result = write_config_atomic(rendered.yaml, target_path)
        except (OSError, ValueError) as exc:
            if previous_identity != coordinator_identity or previous_owner_id != owner_id:
                claim_store.release(coordinator_identity, owner_id, claim.generation)
            sidecar_store.last_error = f"Could not write Zigbee2MQTT configuration: {exc}"
            raise HTTPException(status_code=400, detail=sidecar_store.last_error) from exc

        rendered.config_path = write_result.config_path
        rendered.config_hash = write_result.config_hash
        sidecar_store.current_config = bridge_config
        if topic_prefix:
            mqtt_gateway.configure(bridge_config.mqtt)
        sidecar_store.current_render = rendered
        sidecar_store.config_path = write_result.config_path
        sidecar_store.config_hash = write_result.config_hash
        sidecar_store.last_error = None
        sidecar_store.coordinator_identity = coordinator_identity
        sidecar_store.coordinator_owner_id = owner_id
        sidecar_store.coordinator_claim_generation = claim.generation
        if previous_identity and previous_owner_id and previous_identity != coordinator_identity:
            claim_store.release(previous_identity, previous_owner_id, previous_generation)

    registry.set(config.id, entry)
    registry.update_state(
        config.id,
        {
            "connected": True,
            "zigbee_network_topology": (
                sidecar_store.last_network_map.model_dump(mode="json", exclude={"server"})
                if sidecar_store.last_network_map
                else None
            ),
            "host": config.host,
            "alias": config.alias,
            "config_id": entry["config_id"],
        },
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    config = entry.get("config") or {}
    coordinator_identity = config.get("coordinator_identity")
    if coordinator_identity:
        owner_id = claim_owner_id()
        claim_store.release(
            stable_coordinator_identity(coordinator_identity),
            owner_id,
            sidecar_store.coordinator_claim_generation,
        )
        if sidecar_store.coordinator_owner_id == owner_id:
            sidecar_store.coordinator_identity = None
            sidecar_store.coordinator_owner_id = None
            sidecar_store.coordinator_claim_generation = None
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True
