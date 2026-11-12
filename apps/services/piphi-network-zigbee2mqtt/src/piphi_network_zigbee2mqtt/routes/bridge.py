from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..adapter_detector import discover_adapters
from ..bridge_models import (
    ApplyBridgeRequest,
    ApplyBridgeResponse,
    DeviceListRequest,
    MqttCheckRequest,
    NetworkMapRequest,
    PermitJoinRequest,
    PrerequisiteCheckRequest,
    SupervisorLogsRequest,
    SupervisorRequest,
    WriteConfigRequest,
)
from ..broker_health import check_mqtt_tcp
from ..config_renderer import render_zigbee2mqtt_config
from ..config_store import write_config_atomic
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
    return sidecar_store.snapshot()


@router.get("/adapters")
async def adapters():
    return {"adapters": discover_adapters()}


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
    sidecar_store.current_config = payload.config
    sidecar_store.current_render = rendered
    sidecar_store.config_path = payload.config_path
    sidecar_store.config_hash = rendered.config_hash
    sidecar_store.last_error = None
    return rendered


@router.post("/config/write")
async def write_config(payload: WriteConfigRequest):
    rendered = render_zigbee2mqtt_config(payload.config)
    target_path = payload.config_path or f"{payload.config.data_path.rstrip('/')}/configuration.yaml"
    write_result = write_config_atomic(rendered.yaml, target_path)
    rendered.config_path = write_result.config_path
    sidecar_store.current_config = payload.config
    sidecar_store.current_render = rendered
    sidecar_store.config_path = write_result.config_path
    sidecar_store.config_hash = write_result.config_hash
    sidecar_store.last_error = None
    return {"rendered": rendered, "write": write_result}


@router.post("/apply")
async def apply_bridge(payload: ApplyBridgeRequest) -> ApplyBridgeResponse:
    rendered = render_zigbee2mqtt_config(payload.config)
    target_path = payload.config_path or f"{payload.config.data_path.rstrip('/')}/configuration.yaml"
    write_result = write_config_atomic(rendered.yaml, target_path)
    rendered.config_path = write_result.config_path
    restart_required = _restart_required(payload.restart_policy, write_result.changed)

    supervisor_result = None
    if restart_required and payload.supervisor is not None:
        supervisor_result = await supervise("restart", payload.supervisor)
        sidecar_store.last_supervisor = supervisor_result

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


def _apply_message(policy: str, changed: bool, restart_required: bool) -> str:
    if restart_required:
        return "configuration applied; restart requested"
    if not changed:
        return "configuration unchanged; restart skipped"
    if policy == "never":
        return "configuration changed; restart skipped by policy"
    return "configuration applied"
