from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException

from piphi_network_i2c import sensors, state


def test_bus_operations_at_different_addresses_and_scan_are_serialized() -> None:
    configs = [
        sensors.SensorConfig(adapter="mock", adapter_id="display-one", address=0x76),
        sensors.SensorConfig(adapter="mock", adapter_id="display-two", address=0x77),
        sensors.SensorConfig(adapter="mock", adapter_id="display-scan", address=None, allow_scan=True),
    ]
    active = 0
    maximum = 0
    guard = threading.Lock()

    def operation(_config):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with guard:
            active -= 1

    threads = [
        threading.Thread(target=sensors.run_serialized, args=(config, operation))
        for config in configs
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert maximum == 1


def test_canonical_target_key_ignores_caller_display_identity() -> None:
    first = sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x76, adapter_id="display-one")
    second = sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x76, adapter_id="display-two")

    assert sensors.target_key(first) == sensors.target_key(second)
    assert sensors.target_key(
        sensors.SensorConfig(adapter="mock", sensor_model="bme280", adapter_id="display-one")
    ) == sensors.target_key(
        sensors.SensorConfig(
            adapter="mock", sensor_model="bme280", address=0x76, adapter_id="display-two"
        )
    )


def test_concurrent_duplicate_claims_with_different_display_ids_allow_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    configs = [
        state.I2CSensorRuntimeConfig(
            id="claim-one", adapter="mock", adapter_id="display-one", sensor_model="bme280"
        ),
        state.I2CSensorRuntimeConfig(
            id="claim-two", adapter="mock", adapter_id="display-two", address="0x76", sensor_model="bme680"
        ),
    ]

    reads = 0

    def read_once(config):
        nonlocal reads
        reads += 1
        return sensors.mock_state(config)

    monkeypatch.setattr(state, "read_state", read_once)

    async def apply_both():
        return await asyncio.gather(*(state.apply_config(config) for config in configs), return_exceptions=True)

    results = asyncio.run(apply_both())

    conflicts = [result for result in results if isinstance(result, HTTPException) and result.status_code == 409]
    assert len(conflicts) == 1
    assert reads == 1
    assert len(state.registry.entries) == 1
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()


def test_operation_deadline_and_queue_saturation(monkeypatch: pytest.MonkeyPatch) -> None:
    config = sensors.SensorConfig(adapter="mock")
    monkeypatch.setattr(state, "OPERATION_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(TimeoutError, match="service deadline"):
        asyncio.run(state.run_hardware_operation(config, lambda _config: time.sleep(0.05)))
    acquired = [state._operation_slots.acquire(timeout=1) for _ in range(8)]
    try:
        with pytest.raises(RuntimeError, match="queue is full"):
            asyncio.run(state.run_hardware_operation(config, lambda _config: None))
    finally:
        for did_acquire in acquired:
            if did_acquire:
                state._operation_slots.release()


@pytest.mark.parametrize(
    ("error", "classification"),
    [(PermissionError(), "permission_denied"), (FileNotFoundError(), "unavailable"), (BlockingIOError(), "busy_or_driver_owned")],
)
def test_error_classification_is_privacy_safe(error: BaseException, classification: str) -> None:
    assert state.classify_hardware_error(error) == classification
    payload = state.unavailable_state(error, previous={"connected": True})
    assert payload == {"connected": False, "availability": "stale", "stale": True, "error_class": classification}


def test_diagnostics_redact_paths_ids_and_raw_adapter_identity() -> None:
    diagnostics = state.diagnostics_payload()
    encoded = repr(diagnostics)
    assert "active_config_ids" not in encoded
    assert "device_nodes" not in encoded
    assert "/dev/" not in encoded


def test_manifest_requires_private_core_port_and_dynamic_device_gid() -> None:
    container = state.MANIFEST["runtime"]["linux"]["container"]

    assert container["ports"] == [{"container": 3674, "protocol": "tcp"}]
    assert container["group_add"] == [
        {"source": "device_gid", "path": "/dev/i2c-1", "required": True}
    ]
    assert state.MANIFEST["runtime_contract"] == {
        "version": 1,
        "port_binding": "core_allocated",
        "port_env": "PIPHI_I2C_PORT",
    }
