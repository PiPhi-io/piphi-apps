from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException

from piphi_network_spi import sensors, state


def test_same_target_with_different_display_ids_is_serialized() -> None:
    configs = [
        sensors.SensorConfig(adapter="mock", adapter_id="display-one", chip_select=0),
        sensors.SensorConfig(adapter="mock", adapter_id="display-two", chip_select=0),
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

    threads = [threading.Thread(target=sensors.run_serialized, args=(config, operation)) for config in configs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert maximum == 1
    assert sensors.target_key(configs[0]) == sensors.target_key(configs[1])


def test_concurrent_duplicate_claims_with_different_display_ids_allow_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    configs = [
        state.SPISensorRuntimeConfig(
            id="claim-one", adapter="mock", adapter_id="display-one", chip_select=0, sensor_model="bme280"
        ),
        state.SPISensorRuntimeConfig(
            id="claim-two", adapter="mock", adapter_id="display-two", chip_select=0, sensor_model="bme680"
        ),
    ]

    async def apply_both():
        return await asyncio.gather(*(state.apply_config(config) for config in configs), return_exceptions=True)

    results = asyncio.run(apply_both())

    conflicts = [result for result in results if isinstance(result, HTTPException) and result.status_code == 409]
    assert len(conflicts) == 1
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


def test_classified_stale_state_and_private_diagnostics() -> None:
    payload = state.unavailable_state(PermissionError("/dev/spidev0.0 denied"), previous={"connected": True})
    assert payload == {
        "connected": False,
        "availability": "stale",
        "stale": True,
        "error_class": "permission_denied",
    }
    encoded = repr(state.diagnostics_payload())
    assert "active_config_ids" not in encoded
    assert "device_nodes" not in encoded
    assert "/dev/" not in encoded
