from __future__ import annotations

import asyncio
import threading
import time

import pytest

from piphi_network_i2c import sensors, state


def test_per_adapter_operations_are_serialized() -> None:
    config = sensors.SensorConfig(adapter="mock", adapter_id="adapter01")
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

    threads = [threading.Thread(target=sensors.run_serialized, args=(config, operation)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert maximum == 1


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
