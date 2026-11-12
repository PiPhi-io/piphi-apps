from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from piphi_runtime_kit_python import (
    EventClient,
    RuntimeProcessState,
    TelemetryClient,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    dispatch_event_delivery,
    dispatch_telemetry_delivery,
    schedule_event_delivery,
    schedule_telemetry_delivery,
)

from .contract import CAPABILITIES, COMMANDS
from .mqtt_runtime import (
    ZigbeeMqttError,
    ZigbeeMqttSubscriber,
    ZigbeeMqttSubscription,
    normalize_state_payload,
    subscriptions_for_entry,
)
from .schemas import DeviceConfig
from .settings import DEFAULT_MQTT_BASE_TOPIC, DEFAULT_MQTT_SERVER, INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .zigbee_devices import capability_metadata_from_exposes, infer_capabilities, normalize_device_id, normalize_exposes

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
event_client = starter.event_client
config_sync = starter.config_sync

capabilities = CAPABILITIES
commands = COMMANDS
mqtt_subscribers: dict[str, ZigbeeMqttSubscriber] = {}
mqtt_subscription_errors: dict[str, str] = {}
logger = logging.getLogger(__name__)


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    device_id = _resolve_zigbee_device_id(config)
    config_id = _entry_id_for_config(config)
    capabilities = config.capabilities or infer_capabilities(config.definition)
    mqtt_base_topic = config.mqtt_base_topic or DEFAULT_MQTT_BASE_TOPIC
    mqtt_topic = config.mqtt_topic or f"{mqtt_base_topic.strip('/')}/{config.friendly_name}"
    exposes = config.exposes or normalize_exposes(config.definition)
    capability_metadata = config.capability_metadata or capability_metadata_from_exposes(exposes)
    return {
        **identity,
        "config_id": config_id,
        "device_id": device_id,
        "friendly_name": config.friendly_name,
        "ieee_address": config.ieee_address,
        "alias": config.alias,
        "model_id": config.model_id,
        "vendor": config.vendor,
        "description": config.description,
        "device_type": config.device_type,
        "mqtt_server": config.mqtt_server or DEFAULT_MQTT_SERVER,
        "mqtt_base_topic": mqtt_base_topic,
        "mqtt_topic": mqtt_topic,
        "sidecar_base_url": config.sidecar_base_url,
        "capabilities": capabilities,
        "capability_metadata": capability_metadata,
        "exposes": exposes,
        "definition": config.definition,
        "config": config.model_dump(),
    }


def _resolve_zigbee_device_id(config: DeviceConfig) -> str:
    configured_device_id = str(config.device_id or "").strip()
    physical_device_id = normalize_device_id(config.ieee_address or config.friendly_name)
    if configured_device_id and not (_looks_like_uuid(configured_device_id) and physical_device_id):
        return configured_device_id
    return physical_device_id or configured_device_id


def _looks_like_uuid(value: Any) -> bool:
    try:
        UUID(str(value or "").strip())
    except (TypeError, ValueError):
        return False
    return True


def _entry_id_for_config(config: DeviceConfig) -> str:
    return str(config.config_id or config.id).strip()


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity=severity,
    )
    registry.append_event(event)
    return event


def emit_security_transition_events(
    entry: dict[str, Any],
    previous_state: dict[str, Any],
    state_update: dict[str, Any],
) -> None:
    for capability, event_types, severity in (
        (
            "smoke",
            ("zigbee.safety.smoke.detected", "zigbee.safety.smoke.cleared"),
            "critical",
        ),
        (
            "carbon_monoxide",
            (
                "zigbee.safety.carbon_monoxide.detected",
                "zigbee.safety.carbon_monoxide.cleared",
            ),
            "critical",
        ),
        (
            "water_leak",
            ("zigbee.safety.leak.detected", "zigbee.safety.leak.cleared"),
            "warning",
        ),
    ):
        if capability not in previous_state or capability not in state_update:
            continue
        previous_value = previous_state.get(capability)
        current_value = state_update.get(capability)
        if (
            previous_value == current_value
            or not isinstance(previous_value, bool)
            or not isinstance(current_value, bool)
        ):
            continue
        _deliver_security_event(
            entry=entry,
            event_type=event_types[0] if current_value else event_types[1],
            payload={
                "capability": capability,
                "previous_value": previous_value,
                "current_value": current_value,
            },
            severity=severity,
        )


def _deliver_security_event(
    *,
    entry: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
    severity: str,
) -> None:
    append_runtime_event(event_type, entry, payload, severity)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(
            target=_deliver_security_event_from_thread,
            kwargs={
                "entry": dict(entry),
                "event_type": event_type,
                "payload": dict(payload),
                "severity": severity,
            },
            daemon=True,
        ).start()
        return
    schedule_event_delivery(
        process_state=runtime.process_state,
        event_client=event_client,
        auth_context=runtime.auth,
        event_type=event_type,
        device=entry,
        payload=payload,
        source=INTEGRATION_ID,
        severity=severity,
        on_skipped=_log_event_skipped,
        on_error=_log_event_error,
    )


def _deliver_security_event_from_thread(
    *,
    entry: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
    severity: str,
) -> None:
    async def send() -> None:
        isolated_client = EventClient(
            process_state=RuntimeProcessState(),
            core_base_url=event_client.core_base_url,
            events_ingest_path=event_client.events_ingest_path,
            timeout_seconds=event_client.timeout_seconds,
        )
        await dispatch_event_delivery(
            event_client=isolated_client,
            auth_context=runtime.auth,
            event_type=event_type,
            device=entry,
            payload=payload,
            source=INTEGRATION_ID,
            severity=severity,
            on_skipped=_log_event_skipped,
            on_error=_log_event_error,
        )

    try:
        asyncio.run(send())
    except Exception as exc:
        _log_event_error(exc, {"event_type": event_type})


def _log_event_skipped(reason: str, context: dict[str, Any]) -> None:
    logger.debug("zigbee_event_skipped reason=%s context=%s", reason, context)


def _log_event_error(exc: Exception, context: dict[str, Any]) -> None:
    logger.warning("zigbee_event_delivery_failed error=%s context=%s", exc, context)


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    entry_id = _entry_id_for_config(config)
    if config.id != entry_id:
        registry.remove(config.id)
    registry.set(entry_id, entry)
    registry.update_state(
        entry_id,
        {
            "connected": True,
            "availability": True,
            "friendly_name": config.friendly_name,
            "ieee_address": config.ieee_address,
            "alias": config.alias,
            "config_id": entry["config_id"],
            "mqtt_server": entry["mqtt_server"],
            "mqtt_topic": entry["mqtt_topic"],
        },
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "zigbee.config.applied",
        entry,
        {
            "friendly_name": config.friendly_name,
            "ieee_address": config.ieee_address,
            "alias": config.alias,
        },
    )
    reconcile_mqtt_subscriptions()


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "zigbee.config.removed",
        entry,
        {"friendly_name": entry.get("friendly_name"), "alias": entry.get("alias")},
    )
    reconcile_mqtt_subscriptions()
    return True


def reconcile_mqtt_subscriptions() -> None:
    desired = _subscriptions_by_server()
    for server in list(mqtt_subscribers):
        if server not in desired:
            mqtt_subscribers.pop(server).stop()
            mqtt_subscription_errors.pop(server, None)
    for server, subscriptions in desired.items():
        existing = mqtt_subscribers.get(server)
        if existing and set(existing.topics) == {subscription.topic for subscription in subscriptions}:
            continue
        if existing:
            existing.stop()
        subscriber = ZigbeeMqttSubscriber(
            server=server,
            subscriptions=subscriptions,
            on_payload=_handle_mqtt_payload,
        )
        try:
            subscriber.start()
        except ZigbeeMqttError as exc:
            mqtt_subscription_errors[server] = str(exc)
        mqtt_subscribers[server] = subscriber


def stop_mqtt_subscriptions() -> None:
    for subscriber in mqtt_subscribers.values():
        subscriber.stop()
    mqtt_subscribers.clear()
    mqtt_subscription_errors.clear()


def mqtt_subscription_snapshot() -> dict[str, Any]:
    return {
        "running": any(subscriber.status in {"starting", "running"} for subscriber in mqtt_subscribers.values()),
        "servers": {
            server: {
                **subscriber.snapshot(),
                "error": mqtt_subscription_errors.get(server),
            }
            for server, subscriber in sorted(mqtt_subscribers.items())
        },
    }


def _subscriptions_by_server() -> dict[str, list[ZigbeeMqttSubscription]]:
    grouped: dict[str, list[ZigbeeMqttSubscription]] = {}
    for entry in registry.entries.values():
        server = str(entry.get("mqtt_server") or DEFAULT_MQTT_SERVER)
        subscriptions = subscriptions_for_entry(entry)
        if subscriptions:
            grouped.setdefault(server, []).extend(subscriptions)
    return grouped


def _handle_mqtt_payload(subscription: ZigbeeMqttSubscription, payload: dict[str, Any]) -> None:
    entry = registry.get(subscription.config_id)
    if entry is None:
        return
    state_update = normalize_state_payload(payload)
    current_snapshot = registry.state_snapshots.get(subscription.config_id)
    current_state = current_snapshot.get("state") if isinstance(current_snapshot, dict) else {}
    if not isinstance(current_state, dict):
        current_state = {}
    emit_security_transition_events(entry, current_state, state_update)
    registry.update_state(
        subscription.config_id,
        {
            **current_state,
            **state_update,
            "mqtt_topic": entry.get("mqtt_topic"),
            "mqtt_server": entry.get("mqtt_server"),
        },
        device_id=subscription.device_id,
    )
    append_runtime_event(
        "device.state_changed",
        entry,
        {
            "topic": subscription.topic,
            "payload": payload,
            "state": state_update,
        },
    )
    deliver_state_telemetry(entry, subscription.device_id, state_update)


def deliver_state_telemetry(
    entry: dict[str, Any],
    device_id: str,
    state_update: dict[str, Any],
) -> None:
    metrics = _telemetry_metrics_from_state(state_update)
    if not metrics:
        return

    container_id = str(entry.get("container_id") or "").strip() or None
    config_id = str(entry.get("config_id") or "").strip() or None
    resolved_device_id = str(device_id or entry.get("device_id") or entry.get("config_id") or "").strip()
    if not resolved_device_id:
        return

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        thread = threading.Thread(
            target=_deliver_state_telemetry_from_thread,
            kwargs={
                "container_id": container_id,
                "config_id": config_id,
                "device_id": resolved_device_id,
                "metrics": metrics,
            },
            daemon=True,
        )
        thread.start()
        return

    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        device_id=resolved_device_id,
        config_id=config_id,
        container_id=container_id,
        metrics=metrics,
        on_skipped=_log_telemetry_skipped,
        on_error=_log_telemetry_error,
    )


def _telemetry_metrics_from_state(state_update: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in state_update.items()
        if isinstance(value, (bool, int, float, str))
        and key not in {"mqtt_server", "mqtt_topic"}
    }


def _deliver_state_telemetry_from_thread(
    *,
    container_id: str | None,
    config_id: str | None,
    device_id: str,
    metrics: dict[str, Any],
) -> None:
    async def send() -> None:
        isolated_client = TelemetryClient(
            process_state=RuntimeProcessState(),
            core_base_url=telemetry.core_base_url,
            telemetry_path=telemetry.telemetry_path,
            timeout_seconds=telemetry.timeout_seconds,
        )
        await dispatch_telemetry_delivery(
            telemetry_client=isolated_client,
            auth_context=runtime.auth,
            device_id=device_id,
            config_id=config_id,
            container_id=container_id,
            metrics=metrics,
            on_skipped=_log_telemetry_skipped,
            on_error=_log_telemetry_error,
        )

    try:
        asyncio.run(send())
    except Exception as exc:
        _log_telemetry_error(exc, {"device_id": device_id, "container_id": container_id})


def _log_telemetry_skipped(reason: str, context: dict[str, Any]) -> None:
    logger.debug("zigbee_telemetry_skipped reason=%s context=%s", reason, context)


def _log_telemetry_error(exc: Exception, context: dict[str, Any]) -> None:
    logger.warning("zigbee_telemetry_delivery_failed error=%s context=%s", exc, context)
