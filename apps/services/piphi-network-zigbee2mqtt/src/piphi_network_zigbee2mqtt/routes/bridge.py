from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..adapter_detector import discover_adapters
from ..bridge_models import (
    ApplyBridgeRequest,
    ApplyBridgeResponse,
    CoordinatorMigrationApplyRequest,
    CoordinatorMigrationApplyResponse,
    CoordinatorMigrationPlanRequest,
    CoordinatorProbeRequest,
    DeviceListRequest,
    EncryptedBackupExportRequest,
    EncryptedBackupImportRequest,
    MqttCheckRequest,
    MqttMessagesRequest,
    MqttPublishRequest,
    NetworkBackupRequest,
    NetworkMapRequest,
    NetworkRestoreRequest,
    PermitJoinRequest,
    PrerequisiteCheckRequest,
    SupervisorLogsRequest,
    SupervisorRequest,
    WriteBridgeRequest,
    WriteConfigRequest,
)
from ..broker_health import check_mqtt_tcp
from ..config_renderer import render_zigbee2mqtt_config
from ..config_store import write_config_atomic
from ..coordinator_claims import (
    CoordinatorClaimConflict,
    claim_owner_id,
    claim_store,
    stable_coordinator_identity,
)
from ..coordinator_migration import migration_plan_id, plan_coordinator_migration
from ..coordinator_probe import probe_coordinator
from ..mqtt_gateway import mqtt_gateway
from ..network_backup import (
    create_network_backup,
    export_encrypted_backup,
    import_encrypted_backup,
    restore_network_backup,
    verify_network_backup,
)
from ..state import sidecar_store
from ..supervisor import check_prerequisites, supervise, supervisor_logs
from ..zigbee2mqtt_mqtt import (
    Zigbee2MqttMqttClient,
    Zigbee2MqttMqttError,
    resolve_mqtt_settings,
)

router = APIRouter(prefix="/v1", tags=["zigbee2mqtt-bridge"])


@router.get("/snapshot")
async def snapshot():
    payload = sidecar_store.snapshot().model_dump(mode="json")
    payload["managed_mqtt"] = mqtt_gateway.snapshot()
    return payload


@router.post("/mqtt/messages")
async def mqtt_messages(payload: MqttMessagesRequest):
    try:
        messages = mqtt_gateway.messages(
            payload.topics,
            after_sequence=payload.after_sequence,
        )
    except (ValueError, Zigbee2MqttMqttError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "messages": [
            {
                "sequence": message.sequence,
                "topic": message.topic,
                "payload": message.payload,
            }
            for message in messages
        ],
        "sequence": max(
            [payload.after_sequence, *(message.sequence for message in messages)]
        ),
    }


@router.post("/mqtt/publish")
async def mqtt_publish(payload: MqttPublishRequest):
    try:
        return mqtt_gateway.publish_json(
            payload.topic,
            payload.payload,
            dry_run=payload.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Zigbee2MqttMqttError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/adapters")
async def adapters():
    return {"adapters": discover_adapters()}


@router.post("/coordinator/probe")
async def coordinator_probe(payload: CoordinatorProbeRequest):
    try:
        return probe_coordinator(payload.port)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/network-backup")
async def network_backup(payload: NetworkBackupRequest):
    try:
        return create_network_backup(payload.data_path, adapter_family=payload.adapter_family)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/network-backup/export")
async def network_backup_export(payload: EncryptedBackupExportRequest):
    try:
        return export_encrypted_backup(
            backup_path=payload.backup_path,
            expected_sha256=payload.backup_sha256,
            passphrase=payload.passphrase,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/network-backup/import")
async def network_backup_import(payload: EncryptedBackupImportRequest):
    try:
        return import_encrypted_backup(
            data_path=payload.data_path,
            export_path=payload.export_path,
            expected_sha256=payload.export_sha256,
            passphrase=payload.passphrase,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/coordinator-migration/plan")
async def coordinator_migration_plan(payload: CoordinatorMigrationPlanRequest):
    try:
        return plan_coordinator_migration(payload, probe=probe_coordinator)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/coordinator-migration/apply", response_model=CoordinatorMigrationApplyResponse)
async def coordinator_migration_apply(payload: CoordinatorMigrationApplyRequest):
    if not payload.confirm_migration:
        raise HTTPException(status_code=400, detail="Coordinator migration requires explicit confirmation.")
    plan_request = CoordinatorMigrationPlanRequest.model_validate(
        payload.model_dump(exclude={"plan_id", "confirm_migration"})
    )
    if migration_plan_id(plan_request) != payload.plan_id:
        raise HTTPException(status_code=409, detail="Coordinator migration plan no longer matches the request.")
    try:
        plan_coordinator_migration(plan_request, probe=probe_coordinator)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    identity = stable_coordinator_identity(payload.target_coordinator_identity)
    owner_id = claim_owner_id()
    previous_identity = sidecar_store.coordinator_identity
    previous_owner = sidecar_store.coordinator_owner_id
    claimed_target = previous_identity != identity or previous_owner != owner_id
    restore_result = None
    try:
        claim_store.claim(identity, owner_id)
        restore_result = restore_network_backup(
            data_path=payload.data_path,
            backup_path=payload.backup_path,
            expected_sha256=payload.backup_sha256,
            adapter_family=payload.target_adapter_family,
            compatibility_evidence=payload.compatibility_evidence,
            rollback_adapter_family=payload.source_adapter_family,
        )
        if sidecar_store.current_config is None:
            raise ValueError("A current Zigbee2MQTT configuration is required for guided migration.")
        migrated_config = sidecar_store.current_config.model_copy(
            update={
                "serial": sidecar_store.current_config.serial.model_copy(
                    update={
                        "port": payload.target_coordinator_port,
                        "adapter": payload.target_adapter,
                    }
                )
            }
        )
        rendered = render_zigbee2mqtt_config(migrated_config)
        target_path = f"{payload.data_path.rstrip('/')}/configuration.yaml"
        write_result = write_config_atomic(rendered.yaml, target_path)
        rendered.config_path = write_result.config_path
        rendered.config_hash = write_result.config_hash
        sidecar_store.current_config = migrated_config
        sidecar_store.current_render = rendered
        sidecar_store.config_path = write_result.config_path
        sidecar_store.config_hash = write_result.config_hash
        sidecar_store.coordinator_identity = identity
        sidecar_store.coordinator_owner_id = owner_id
        sidecar_store.last_error = None
    except CoordinatorClaimConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        if restore_result is not None:
            try:
                restore_network_backup(
                    data_path=payload.data_path,
                    backup_path=restore_result.rollback_backup.backup_path,
                    expected_sha256=restore_result.rollback_backup.backup_sha256,
                    adapter_family=payload.source_adapter_family,
                )
            except (OSError, ValueError) as rollback_exc:
                sidecar_store.last_error = "Coordinator migration and automatic rollback both failed."
                raise HTTPException(status_code=500, detail=sidecar_store.last_error) from rollback_exc
        sidecar_store.last_error = f"Coordinator migration failed and was rolled back: {exc}"
        raise HTTPException(status_code=409, detail=sidecar_store.last_error) from exc
    finally:
        if claimed_target and sidecar_store.coordinator_identity != identity:
            claim_store.release(identity, owner_id)

    if previous_identity and previous_owner and previous_identity != identity:
        claim_store.release(previous_identity, previous_owner)
    assert restore_result is not None
    return CoordinatorMigrationApplyResponse(
        migrated=True,
        plan_id=payload.plan_id,
        target_coordinator_identity=identity,
        target_coordinator_port=payload.target_coordinator_port,
        restored_files=restore_result.files,
        rollback_backup=restore_result.rollback_backup,
        message="Coordinator migration restored and configured; Core restart and post-migration verification are required.",
    )


@router.post("/network-restore")
async def network_restore(payload: NetworkRestoreRequest):
    if not payload.confirm_restore:
        raise HTTPException(status_code=400, detail="Network restore requires explicit confirmation.")
    probe = probe_coordinator(payload.coordinator_port)
    if not probe.available:
        raise HTTPException(
            status_code=409,
            detail=probe.message or "Coordinator must be stopped before restore.",
        )
    identity = stable_coordinator_identity(payload.coordinator_identity)
    owner_id = claim_owner_id()
    already_owned = (
        sidecar_store.coordinator_identity == identity
        and sidecar_store.coordinator_owner_id == owner_id
    )
    try:
        claim_store.claim(identity, owner_id)
        result = restore_network_backup(
            data_path=payload.data_path,
            backup_path=payload.backup_path,
            expected_sha256=payload.backup_sha256,
            adapter_family=payload.adapter_family,
        )
        sidecar_store.current_config = None
        sidecar_store.current_render = None
        sidecar_store.config_path = None
        sidecar_store.config_hash = None
        sidecar_store.last_error = None
        return result
    except CoordinatorClaimConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if not already_owned:
            claim_store.release(identity, owner_id)


@router.post("/devices")
async def devices(payload: DeviceListRequest | None = None):
    request = payload or DeviceListRequest()
    try:
        mqtt_settings = resolve_mqtt_settings(
            current=sidecar_store.current_config.mqtt if sidecar_store.current_config else None,
            server=request.server,
            base_topic=request.base_topic,
        )
        result = await Zigbee2MqttMqttClient(
            mqtt=mqtt_settings,
            timeout_seconds=request.timeout_seconds,
        ).list_devices(dry_run=request.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Zigbee2MqttMqttError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    sidecar_store.last_devices = result
    return result


@router.get("/devices")
async def devices_get():
    return await devices(DeviceListRequest())


@router.post("/network-map")
async def network_map(payload: NetworkMapRequest | None = None):
    request = payload or NetworkMapRequest()
    try:
        mqtt_settings = resolve_mqtt_settings(
            current=sidecar_store.current_config.mqtt if sidecar_store.current_config else None,
            server=request.server,
            base_topic=request.base_topic,
        )
        result = await Zigbee2MqttMqttClient(
            mqtt=mqtt_settings,
            timeout_seconds=request.timeout_seconds,
        ).network_map(routes=request.routes, dry_run=request.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Zigbee2MqttMqttError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    sidecar_store.last_network_map = result
    return result


@router.get("/network-map")
async def network_map_get():
    if sidecar_store.last_network_map is None:
        raise HTTPException(status_code=404, detail="No Zigbee network map has been scanned yet.")
    return sidecar_store.last_network_map


@router.post("/permit-join")
async def permit_join(payload: PermitJoinRequest):
    try:
        mqtt_settings = resolve_mqtt_settings(
            current=sidecar_store.current_config.mqtt if sidecar_store.current_config else None,
            server=payload.server,
            base_topic=payload.base_topic,
        )
        result = await Zigbee2MqttMqttClient(
            mqtt=mqtt_settings,
            timeout_seconds=payload.timeout_seconds,
        ).permit_join(
            value=payload.value,
            time=payload.time,
            device=payload.device,
            dry_run=payload.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Zigbee2MqttMqttError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    sidecar_store.last_permit_join = result
    return result


@router.post("/config/render")
async def render_config(payload: WriteConfigRequest):
    rendered = render_zigbee2mqtt_config(payload.config)
    if payload.config_path:
        rendered.config_path = payload.config_path
    sidecar_store.current_render = rendered
    sidecar_store.last_error = None
    return rendered


@router.post("/config/write")
async def write_config(payload: WriteBridgeRequest):
    _require_safe_network_change(payload)
    coordinator_identity, owner_id = _claim_coordinator(payload)
    rendered = render_zigbee2mqtt_config(payload.config)
    target_path = payload.config_path or f"{payload.config.data_path.rstrip('/')}/configuration.yaml"
    try:
        write_result = write_config_atomic(rendered.yaml, target_path)
    except (OSError, ValueError) as exc:
        claim_store.release(coordinator_identity, owner_id)
        raise HTTPException(status_code=400 if isinstance(exc, ValueError) else 500, detail=str(exc)) from exc
    rendered.config_path = write_result.config_path
    sidecar_store.current_config = payload.config
    sidecar_store.current_render = rendered
    sidecar_store.config_path = write_result.config_path
    sidecar_store.config_hash = write_result.config_hash
    sidecar_store.last_error = None
    sidecar_store.coordinator_identity = coordinator_identity
    sidecar_store.coordinator_owner_id = owner_id
    return {"rendered": rendered, "write": write_result}


@router.post("/apply")
async def apply_bridge(payload: ApplyBridgeRequest) -> ApplyBridgeResponse:
    _require_safe_network_change(payload)
    coordinator_identity, owner_id = _claim_coordinator(payload)
    rendered = render_zigbee2mqtt_config(payload.config)
    target_path = payload.config_path or f"{payload.config.data_path.rstrip('/')}/configuration.yaml"
    try:
        write_result = write_config_atomic(rendered.yaml, target_path)
    except (OSError, ValueError) as exc:
        claim_store.release(coordinator_identity, owner_id)
        raise HTTPException(status_code=400 if isinstance(exc, ValueError) else 500, detail=str(exc)) from exc
    rendered.config_path = write_result.config_path
    restart_required = _restart_required(payload.restart_policy, write_result.changed)

    supervisor_result = None
    if restart_required and payload.supervisor is not None:
        try:
            supervisor_result = await supervise("restart", payload.supervisor)
        except Exception:
            claim_store.release(coordinator_identity, owner_id)
            raise
        sidecar_store.last_supervisor = supervisor_result
        if not supervisor_result.ok:
            claim_store.release(coordinator_identity, owner_id)

    mqtt_result = None
    if payload.mqtt_check is not None:
        server = payload.mqtt_check.server or payload.config.mqtt.server
        mqtt_result = await check_mqtt_tcp(
            server,
            timeout_seconds=payload.mqtt_check.timeout_seconds,
            dry_run=payload.mqtt_check.dry_run,
        )
        sidecar_store.last_mqtt_check = mqtt_result

    sidecar_store.current_config = payload.config
    sidecar_store.current_render = rendered
    sidecar_store.config_path = write_result.config_path
    sidecar_store.config_hash = write_result.config_hash
    sidecar_store.last_error = None
    if supervisor_result is None or supervisor_result.ok:
        sidecar_store.coordinator_identity = coordinator_identity
        sidecar_store.coordinator_owner_id = owner_id
    ok = (supervisor_result.ok if supervisor_result else True) and (mqtt_result.ok if mqtt_result else True)
    return ApplyBridgeResponse(
        ok=ok,
        rendered=rendered,
        write=write_result,
        restart_required=restart_required,
        supervisor=supervisor_result,
        mqtt_check=mqtt_result,
        message=_apply_message(payload.restart_policy, write_result.changed, restart_required),
    )


@router.post("/supervisor/status")
async def supervisor_status(payload: SupervisorRequest):
    result = await supervise("status", payload)
    sidecar_store.last_supervisor = result
    return result


@router.post("/supervisor/start")
async def supervisor_start(payload: SupervisorRequest):
    result = await supervise("start", payload)
    sidecar_store.last_supervisor = result
    return result


@router.post("/supervisor/stop")
async def supervisor_stop(payload: SupervisorRequest):
    result = await supervise("stop", payload)
    sidecar_store.last_supervisor = result
    if result.ok and sidecar_store.coordinator_identity and sidecar_store.coordinator_owner_id:
        claim_store.release(
            sidecar_store.coordinator_identity,
            sidecar_store.coordinator_owner_id,
        )
        sidecar_store.coordinator_identity = None
        sidecar_store.coordinator_owner_id = None
    return result


@router.post("/supervisor/restart")
async def supervisor_restart(payload: SupervisorRequest):
    result = await supervise("restart", payload)
    sidecar_store.last_supervisor = result
    return result


@router.post("/supervisor/logs")
async def logs(payload: SupervisorLogsRequest):
    result = await supervisor_logs(payload)
    sidecar_store.last_supervisor = result
    return result


@router.post("/prerequisites")
async def prerequisites(payload: PrerequisiteCheckRequest):
    return await check_prerequisites(payload)


@router.post("/mqtt/check")
async def mqtt_check(payload: MqttCheckRequest | None = None):
    request = payload or MqttCheckRequest()
    server = request.server
    if not server:
        if sidecar_store.current_config is None:
            raise HTTPException(status_code=400, detail="MQTT server is required before bridge config is rendered.")
        server = sidecar_store.current_config.mqtt.server
    try:
        result = await check_mqtt_tcp(server, timeout_seconds=request.timeout_seconds, dry_run=request.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sidecar_store.last_mqtt_check = result
    return result


def _restart_required(policy: str, changed: bool) -> bool:
    if policy == "always":
        return True
    if policy == "never":
        return False
    return changed


def _require_safe_network_change(payload: WriteConfigRequest) -> None:
    current = sidecar_store.current_config
    if current is None:
        return
    previous = current.advanced
    requested = payload.config.advanced
    identity_changed = (
        previous.pan_id,
        previous.ext_pan_id,
        previous.network_key,
    ) != (
        requested.pan_id,
        requested.ext_pan_id,
        requested.network_key,
    )
    if identity_changed:
        try:
            verify_network_backup(payload.backup_path, payload.backup_sha256)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def _claim_coordinator(payload: WriteBridgeRequest) -> tuple[str, str]:
    coordinator_identity = stable_coordinator_identity(payload.coordinator_identity)
    owner_id = claim_owner_id()
    if sidecar_store.coordinator_identity != coordinator_identity:
        probe = probe_coordinator(payload.config.serial.port)
        if not probe.available:
            raise HTTPException(
                status_code=409,
                detail=probe.message or "Coordinator is unavailable or already in use.",
            )
    try:
        claim_store.claim(coordinator_identity, owner_id)
    except CoordinatorClaimConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return coordinator_identity, owner_id


def _apply_message(policy: str, changed: bool, restart_required: bool) -> str:
    if restart_required:
        return "configuration applied; restart requested"
    if not changed:
        return "configuration unchanged; restart skipped"
    if policy == "never":
        return "configuration changed; restart skipped by policy"
    return "configuration applied"
