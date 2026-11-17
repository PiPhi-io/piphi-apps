from __future__ import annotations

import asyncio
import time

import pytest

from piphi_network_spi import sensors, state


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
