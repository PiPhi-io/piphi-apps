from __future__ import annotations

import asyncio
import errno
import json
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    RuntimeConfig,
    RuntimeConfigSnapshot,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
    validate_typed_configs,
)
from pydantic import Field, model_validator

from .sensors import (
    OPERATION_TIMEOUT_SECONDS,
    SensorConfig,
    adapter_fingerprint,
    hardware_diagnostics,
    normalize_config,
    read_state,
    run_serialized,
    target_key,
)

INTEGRATION_ID = "piphi-network-spi"
INTEGRATION_NAME = "PiPhi Network SPI Sensors"
INTEGRATION_VERSION = "0.1.4"

PACKAGE_MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"
MANIFEST_PATH = PACKAGE_MANIFEST_PATH if PACKAGE_MANIFEST_PATH.exists() else Path(__file__).resolve().parents[1] / "manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text())
UI_CONFIG_SCHEMA = {
    "fields": [
        {"name": "adapter", "label": "Adapter", "type": "select", "required": True, "options": ["mock"], "default": "mock"},
        {"name": "adapter_id", "label": "Opaque adapter ID", "type": "text", "required": False},
        {"name": "bus", "label": "SPI Bus", "type": "number", "required": True, "default": 0},
        {"name": "chip_select", "label": "Chip Select", "type": "number", "required": True, "default": 0},
        {"name": "sensor_model", "label": "Sensor Model", "type": "select", "required": True, "options": ["auto", "bme680", "bme280", "bmp280"], "default": "auto"},
        {"name": "alias", "label": "Alias", "type": "text", "required": False},
        {"name": "baudrate", "label": "Baudrate", "type": "number", "required": True, "default": 100000},
        {"name": "poll_interval_seconds", "label": "Poll Interval", "type": "number", "required": True, "default": 30},
    ]
}


class SPISensorRuntimeConfig(RuntimeConfig):
    adapter: Literal["mock"] = "mock"
    adapter_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[a-z0-9_-]+$")
    bus: int = Field(default=0, ge=0, le=0, strict=True)
    chip_select: int = Field(default=0, ge=0, le=1, strict=True)
    sensor_model: Literal["auto", "bme680", "bme280", "bmp280"] = "auto"
    baudrate: int = Field(default=100000, ge=10_000, le=1_000_000, strict=True)
    poll_interval_seconds: int = Field(default=30, ge=5, le=3600, strict=True)
    alias: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_hardware_target(self) -> SPISensorRuntimeConfig:
        normalize_config(self.model_dump())
        return self


starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
config_sync = starter.config_sync
telemetry_client = starter.telemetry_client
capabilities = MANIFEST.get("capabilities", {})
commands = MANIFEST.get("commands", {})

TELEMETRY_UNITS = {
    key: value["unit"]
    for key, value in capabilities.items()
    if isinstance(value, dict) and value.get("kind") == "sensor" and value.get("unit")
}


def config_to_sensor_config(config: SPISensorRuntimeConfig) -> SensorConfig:
    return normalize_config(config.model_dump())


def typed_snapshot_configs(snapshot: RuntimeConfigSnapshot) -> list[SPISensorRuntimeConfig]:
    return validate_typed_configs(
        [
            config.model_dump() if hasattr(config, "model_dump") else config
            for config in snapshot.configs
        ],
        SPISensorRuntimeConfig,
    )


def primary_config() -> SPISensorRuntimeConfig:
    entry = registry.primary_entry()
    if entry is None:
        return SPISensorRuntimeConfig(id="spi-dev", adapter="mock", sensor_model="bme280")
    return SPISensorRuntimeConfig.model_validate(entry["config"])


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


def entry_for_config(config: SPISensorRuntimeConfig) -> dict[str, Any]:
    sensor_config = config_to_sensor_config(config)
    adapter_uid = adapter_fingerprint(sensor_config)
    model = "bme280" if sensor_config.adapter == "mock" and sensor_config.sensor_model == "auto" else sensor_config.sensor_model
    device = {
        "id": config.device_id or f"spi-{adapter_uid}-{sensor_config.chip_select}",
        "name": config.alias or "SPI Sensor",
        "device_id": config.device_id or f"spi-{adapter_uid}-{sensor_config.chip_select}",
        "adapter_uid": adapter_uid,
        "adapter": sensor_config.adapter,
        "bus": sensor_config.bus,
        "chip_select": sensor_config.chip_select,
        "model": model,
        "baudrate": sensor_config.baudrate,
    }
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "device_id": config.device_id or device.get("device_id") or identity["device_id"],
        "name": config.alias or device.get("name") or "SPI Sensor",
        "config": config.model_dump(),
        "device": device,
    }


def entity_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
    device = entry.get("device") if isinstance(entry.get("device"), dict) else {}
    model = str(device.get("model") or "").lower()
    entity_capabilities = ["connected", "temperature_c", "humidity_percent", "pressure_hpa", "refresh"]
    if model == "bme680":
        entity_capabilities.append("gas_ohms")
    return {
        "id": str(device.get("id") or entry["config_id"]),
        "name": str(entry.get("name") or device.get("name") or "SPI Sensor"),
        "config_id": entry["config_id"],
        "device_id": entry["device_id"],
        "device_class": "environmental_sensor",
        "entity_type": "sensor",
        "capabilities": entity_capabilities,
        "available_commands": [{"id": "refresh", "label": "Refresh", "kind": "action"}],
        "dashboard": {
            "allowed_widgets": ["sensor-card", "stat", "line-chart", "air-quality-card", "room-climate-card"],
            "default_widget": "sensor-card",
        },
        "metadata": device,
    }


def append_runtime_event(
    event_type: str,
    entry: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=entry,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity="info",
    )
    registry.append_event(event)
    return event


def schedule_state_telemetry(entry: dict[str, Any], state: dict[str, Any]) -> None:
    metrics = {
        key: value
        for key, value in state.items()
        if key not in {"error", "sampled_at"}
        and isinstance(value, (bool, int, float, str))
    }
    if not metrics:
        return
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry_client,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={key: TELEMETRY_UNITS[key] for key in metrics if key in TELEMETRY_UNITS},
        timestamp=str(state.get("sampled_at")) if state.get("sampled_at") else None,
    )


_claims_guard = threading.Lock()
_claim_reservations: dict[tuple[str, str, int, int], str] = {}
_operation_slots = threading.BoundedSemaphore(8)
_operation_stats: dict[str, dict[str, Any]] = {}


def classify_hardware_error(exc: BaseException) -> str:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM}:
        return "permission_denied"
    if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) == errno.EBUSY:
        return "busy_or_driver_owned"
    if isinstance(exc, (FileNotFoundError, ModuleNotFoundError, ImportError)) or getattr(exc, "errno", None) in {
        errno.ENOENT,
        errno.ENODEV,
        errno.ENXIO,
    }:
        return "unavailable"
    if isinstance(exc, ValueError):
        return "invalid_or_unsupported"
    return "io_error"


def unavailable_state(exc: BaseException, *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "connected": False,
        "availability": "stale" if previous and previous.get("connected") else "unavailable",
        "stale": bool(previous and previous.get("connected")),
        "error_class": classify_hardware_error(exc),
    }


def _record_operation(config: SensorConfig, *, started: float, error: BaseException | None = None) -> None:
    key = adapter_fingerprint(config)
    stats = _operation_stats.setdefault(key, {"attempts": 0, "failures": 0})
    stats["attempts"] += 1
    stats["last_latency_ms"] = round((time.monotonic() - started) * 1000, 2)
    if error is None:
        stats["last_status"] = "available"
        stats["last_error_class"] = None
    else:
        stats["failures"] += 1
        stats["last_status"] = "unavailable"
        stats["last_error_class"] = classify_hardware_error(error)


def _reserve_target(config: SPISensorRuntimeConfig) -> tuple[str, str, int, int]:
    requested = target_key(config_to_sensor_config(config))
    with _claims_guard:
        for existing_id, existing in registry.entries.items():
            if existing_id == config.id:
                continue
            existing_config = SPISensorRuntimeConfig.model_validate(existing["config"])
            if target_key(config_to_sensor_config(existing_config)) == requested:
                raise HTTPException(
                    status_code=409,
                    detail=f"SPI target is already claimed by config_id={existing_id}",
                )
        reservation_owner = _claim_reservations.get(requested)
        if reservation_owner is not None:
            raise HTTPException(
                status_code=409,
                detail=f"SPI target claim is already in progress for config_id={reservation_owner}",
            )
        _claim_reservations[requested] = config.id
    return requested


def _release_target_reservation(requested: tuple[str, str, int, int], config_id: str) -> None:
    with _claims_guard:
        if _claim_reservations.get(requested) == config_id:
            _claim_reservations.pop(requested, None)


def _commit_claim_and_state(
    config: SPISensorRuntimeConfig,
    requested: tuple[str, str, int, int],
    entry: dict[str, Any],
    state: dict[str, Any],
) -> None:
    with _claims_guard:
        if _claim_reservations.get(requested) != config.id:
            raise RuntimeError("SPI target reservation was lost before commit")
        try:
            registry.set(config.id, entry)
            registry.update_state(config.id, state, device_id=entry["device_id"])
        finally:
            _claim_reservations.pop(requested, None)


async def run_hardware_operation(config: SensorConfig, operation: Any) -> Any:
    if not _operation_slots.acquire(blocking=False):
        raise RuntimeError("SPI operation queue is full")

    started = time.monotonic()

    def execute() -> Any:
        try:
            return run_serialized(config, operation)
        finally:
            _operation_slots.release()

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(execute),
            timeout=OPERATION_TIMEOUT_SECONDS,
        )
        _record_operation(config, started=started)
        return result
    except TimeoutError as exc:
        error = TimeoutError("SPI operation exceeded its service deadline")
        _record_operation(config, started=started, error=error)
        raise error from exc
    except Exception as exc:
        _record_operation(config, started=started, error=exc)
        raise


async def apply_config(config: SPISensorRuntimeConfig) -> None:
    entry = entry_for_config(config)
    sensor_config = config_to_sensor_config(config)
    requested = _reserve_target(config)
    try:
        state = await run_hardware_operation(sensor_config, read_state)
        state = {**state, "availability": "available", "stale": False, "error_class": None}
    except Exception as exc:
        _release_target_reservation(requested, config.id)
        raise HTTPException(
            status_code=503,
            detail=f"SPI setup validation failed: {exc}",
        ) from exc
    _commit_claim_and_state(config, requested, entry, state)
    schedule_state_telemetry(entry, state)
    append_runtime_event("spi.config.applied", entry, {"sensor_model": config.sensor_model})


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event("spi.config.removed", entry)
    return True


def read_current_state() -> dict[str, Any]:
    if not registry.ids():
        return {"entries": {}, "state_snapshots": {}}
    return {"entries": registry.entries, "state_snapshots": registry.state_snapshots}


async def refresh_all_state() -> None:
    for config_id in registry.ids():
        entry = get_entry_or_404(config_id)
        config = SPISensorRuntimeConfig.model_validate(entry["config"])
        previous_snapshot = registry.state_snapshots.get(config_id, {})
        previous = previous_snapshot.get("state") if isinstance(previous_snapshot, dict) else None
        try:
            state_payload = await run_hardware_operation(config_to_sensor_config(config), read_state)
            state_payload = {**state_payload, "availability": "available", "stale": False, "error_class": None}
        except Exception as exc:
            state_payload = unavailable_state(exc, previous=previous)
            registry.update_state(config_id, state_payload, device_id=entry["device_id"])
            append_runtime_event("spi.sensor.refresh_failed", entry, {"error_class": state_payload["error_class"]})
            schedule_state_telemetry(entry, state_payload)
            continue
        registry.update_state(config_id, state_payload, device_id=entry["device_id"])
        if previous and previous.get("availability") != "available":
            append_runtime_event("spi.sensor.recovered", entry)
        schedule_state_telemetry(entry, state_payload)


starter.state.provide(refresh_all_state, source=INTEGRATION_ID)


def diagnostics_payload() -> dict[str, Any]:
    return {
        "active_config_count": len(registry.ids()),
        "recent_event_count": len(registry.recent_events),
        "runtime_version": INTEGRATION_VERSION,
        "physical_qualification": "experimental_unverified",
        "adapter_operations": _operation_stats,
        "supported_models": ["bme680", "bme280", "bmp280"],
        "hardware": hardware_diagnostics(),
    }
