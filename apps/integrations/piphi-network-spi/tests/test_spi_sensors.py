from __future__ import annotations

import pytest

from piphi_network_spi import sensors


def test_require_mock_enabled_raises_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_MOCK_HARDWARE", raising=False)

    with pytest.raises(RuntimeError, match="Mock hardware is disabled"):
        sensors.require_mock_enabled()


def test_hardware_diagnostics_exposes_only_used_backends() -> None:
    diagnostics = sensors.hardware_diagnostics()

    assert diagnostics["default_adapter"] == "mock"
    assert diagnostics["supported_adapters"] == ["mock"]
    assert "linux_spi" not in diagnostics
    assert "ft232h" not in diagnostics


def test_discover_devices_probes_instead_of_projecting_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[sensors.SensorConfig] = []
    monkeypatch.setattr(
        sensors,
        "probe_sensor",
        lambda config: probes.append(config) or "bme280",
    )
    devices = sensors.discover_devices(
        sensors.SensorConfig(adapter="linux_spi", bus=0, chip_select=0, sensor_model="bme280")
    )

    assert devices[0]["model"] == "bme280"
    assert len(probes) == 1


def test_normalize_config_rejects_ignored_or_unsafe_settings() -> None:
    with pytest.raises(ValueError, match="mock-only 0.1.5: bus"):
        sensors.normalize_config({"bus": 1, "sensor_model": "bme280"})
    with pytest.raises(ValueError, match="mock-only 0.1.5: chip_select"):
        sensors.normalize_config({"chip_select": 9, "sensor_model": "bme280"})
    with pytest.raises(ValueError, match="mock-only 0.1.5: baudrate"):
        sensors.normalize_config({"baudrate": 1, "sensor_model": "bme280"})
    with pytest.raises(ValueError, match="explicit sensor_model"):
        sensors.normalize_config({"adapter": "linux_spi", "sensor_model": "auto"})
    with pytest.raises(ValueError, match="exact spidev/USB-node selection"):
        sensors.normalize_config({"adapter": "linux_spi", "sensor_model": "bme280"})
    with pytest.raises(ValueError, match="exact spidev/USB-node selection"):
        sensors.normalize_config({"adapter": "ft232h", "sensor_model": "bme280"})


def test_spi_read_passes_baudrate_and_deinitializes_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import ModuleType

    class Handle:
        def __init__(self) -> None:
            self.deinitialized = False

        def deinit(self) -> None:
            self.deinitialized = True

    class FakeSensor(Handle):
        temperature = 21.0
        relative_humidity = 40.0
        pressure = 1000.0

        def __init__(self, spi, cs, *, baudrate) -> None:
            super().__init__()
            self.baudrate = baudrate

    spi = Handle()
    chip_select = Handle()
    created: list[FakeSensor] = []
    monkeypatch.setattr(sensors, "_spi_bus", lambda config: spi)
    monkeypatch.setattr(sensors, "_chip_select", lambda config: chip_select)
    package = ModuleType("adafruit_bme280")
    advanced = ModuleType("adafruit_bme280.advanced")
    advanced.Adafruit_BME280_SPI = lambda *args, **kwargs: created.append(
        FakeSensor(*args, **kwargs)
    ) or created[-1]
    monkeypatch.setitem(sys.modules, "adafruit_bme280", package)
    monkeypatch.setitem(sys.modules, "adafruit_bme280.advanced", advanced)

    payload = sensors.read_bme280(
        sensors.SensorConfig(sensor_model="bme280", baudrate=400_000)
    )

    assert payload["baudrate"] == 400_000
    assert created[0].baudrate == 400_000
    assert created[0].deinitialized is True
    assert chip_select.deinitialized is True
    assert spi.deinitialized is True


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


def test_mock_discovery_has_no_physical_transport_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_MOCK_HARDWARE", "true")

    device = sensors.discover_devices(sensors.SensorConfig(adapter="mock", sensor_model="bme680"))[0]

    assert device["adapter"] == "mock"
    assert {"bus", "chip_select", "baudrate"}.isdisjoint(device)
