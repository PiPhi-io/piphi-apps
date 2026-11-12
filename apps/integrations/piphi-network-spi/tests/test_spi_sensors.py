from __future__ import annotations

import pytest

from piphi_network_spi import sensors


def test_require_mock_enabled_raises_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_MOCK_HARDWARE", raising=False)

    with pytest.raises(RuntimeError, match="Mock hardware is disabled"):
        sensors.require_mock_enabled()


def test_hardware_diagnostics_exposes_ft232h_and_shared_library_keys() -> None:
    diagnostics = sensors.hardware_diagnostics()

    assert "ft232h" in diagnostics
    assert "shared_libraries" in diagnostics


def test_discover_devices_auto_defaults_to_bme280() -> None:
    devices = sensors.discover_devices(
        sensors.SensorConfig(adapter="linux_spi", bus=0, chip_select=0, sensor_model="auto")
    )

    assert devices[0]["model"] == "bme280"


def test_hardware_diagnostics_reports_mock_enabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")

    diagnostics = sensors.hardware_diagnostics()

    assert diagnostics["mock_enabled"] is True


def test_discover_devices_mock_requires_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_MOCK_HARDWARE", raising=False)

    with pytest.raises(RuntimeError, match="Mock hardware is disabled"):
        sensors.discover_devices(
            sensors.SensorConfig(adapter="mock", bus=0, chip_select=0, sensor_model="bme680")
        )
