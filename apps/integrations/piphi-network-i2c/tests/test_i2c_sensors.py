from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from piphi_network_i2c import sensors


def test_require_mock_enabled_raises_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_MOCK_HARDWARE", raising=False)

    with pytest.raises(RuntimeError, match="Mock hardware is disabled"):
        sensors.require_mock_enabled()


def test_scan_blinka_i2c_addresses_returns_empty_when_board_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sensors, "_board_i2c", lambda config: (_ for _ in ()).throw(ImportError("no board")))

    addresses = sensors.scan_blinka_i2c_addresses(
        sensors.SensorConfig(adapter="mcp2221a", bus=1, sensor_model="auto")
    )

    assert addresses == []


def test_hardware_diagnostics_exposes_bridge_support_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLINKA_MCP2221", "true")
    monkeypatch.setenv("BLINKA_FT232H", "1")

    diagnostics = sensors.hardware_diagnostics()

    assert diagnostics["mcp2221a"]["blinka_env_enabled"] is True
    assert "easy_mcp2221" in diagnostics["mcp2221a"]
    assert diagnostics["ft232h"]["blinka_env_enabled"] is True


def test_parse_address_supports_hex_and_decimal() -> None:
    assert sensors.parse_address("0x76") == 0x76
    assert sensors.parse_address("56") == 56


def test_discover_devices_guesses_pmsa003i_for_fixed_address() -> None:
    devices = sensors.discover_devices(
        sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x12, sensor_model="auto")
    )

    assert devices[0]["model"] == "pmsa003i"
    assert devices[0]["address"] == "0x12"


def test_read_state_auto_routes_pmsa003i_by_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sensors,
        "read_pmsa003i",
        lambda config: {"connected": True, "sensor_model": "pmsa003i", "pm2_5_standard_ugm3": 11},
    )

    payload = sensors.read_state(
        sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x12, sensor_model="auto")
    )

    assert payload["sensor_model"] == "pmsa003i"
    assert payload["pm2_5_standard_ugm3"] == 11


def test_scan_blinka_i2c_addresses_returns_empty_when_lock_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeI2C:
        def try_lock(self) -> bool:
            return False

        def scan(self) -> list[int]:
            return [0x76]

        def unlock(self) -> None:
            return None

    monkeypatch.setattr(sensors, "_board_i2c", lambda config: FakeI2C())

    addresses = sensors.scan_blinka_i2c_addresses(
        sensors.SensorConfig(adapter="ft232h", bus=1, sensor_model="auto")
    )

    assert addresses == []


def test_scan_mcp2221_i2c_addresses_uses_easy_mcp2221_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NotAckError(Exception):
        pass

    scanned: list[int] = []
    bus_calls: list[tuple[int, int]] = []

    class FakeMCP:
        def I2C_read(self, address: int) -> bytes:
            scanned.append(address)
            if address in {0x38, 0x76}:
                return b"\x00"
            raise NotAckError()

    class FakeBus:
        def __init__(self) -> None:
            self.mcp = FakeMCP()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    fake_bus = FakeBus()
    fake_module = SimpleNamespace(
        SMBus=lambda bus=1, clock=100000: bus_calls.append((bus, clock)) or fake_bus,
        exceptions=SimpleNamespace(NotAckError=NotAckError),
    )
    monkeypatch.setattr(sensors, "_import_easy_mcp2221", lambda: fake_module)

    addresses = sensors.scan_mcp2221_i2c_addresses(
        sensors.SensorConfig(adapter="mcp2221a", bus=2, sensor_model="auto")
    )

    assert addresses == [0x38, 0x76]
    assert bus_calls == [(2, sensors.DEFAULT_MCP2221_I2C_CLOCK)]
    assert 0x03 in scanned
    assert 0x77 in scanned
    assert fake_bus.closed is True


def test_read_bme280_with_mcp2221_uses_smbus_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBus:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeBME280:
        def __init__(self, *, i2c_dev, i2c_addr) -> None:
            self.i2c_dev = i2c_dev
            self.i2c_addr = i2c_addr

        def get_temperature(self) -> float:
            return 21.234

        def get_humidity(self) -> float:
            return 48.765

        def get_pressure(self) -> float:
            return 1009.432

    fake_bus = FakeBus()
    monkeypatch.setattr(sensors, "_mcp2221_smbus", lambda config: fake_bus)
    monkeypatch.setitem(sys.modules, "bme280", SimpleNamespace(BME280=FakeBME280))

    payload = sensors.read_bme280(
        sensors.SensorConfig(adapter="mcp2221a", bus=1, address=0x76, sensor_model="bme280")
    )

    assert payload["adapter"] == "mcp2221a"
    assert payload["address"] == "0x76"
    assert payload["temperature_c"] == 21.23
    assert payload["humidity_percent"] == 48.77
    assert payload["pressure_hpa"] == 1009.43
    assert fake_bus.closed is True


def test_read_bme680_with_mcp2221_uses_smbus_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBus:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeData:
        temperature = 23.456
        humidity = 52.345
        pressure = 1007.654
        gas_resistance = 14001.25

    class FakeBME680:
        def __init__(self, *, i2c_addr, i2c_device) -> None:
            self.i2c_addr = i2c_addr
            self.i2c_device = i2c_device
            self.data = FakeData()

        def get_sensor_data(self) -> bool:
            return True

    fake_bus = FakeBus()
    monkeypatch.setattr(sensors, "_mcp2221_smbus", lambda config: fake_bus)
    monkeypatch.setitem(
        sys.modules,
        "bme680",
        SimpleNamespace(BME680=FakeBME680, I2C_ADDR_PRIMARY=0x76),
    )

    payload = sensors.read_bme680(
        sensors.SensorConfig(adapter="mcp2221a", bus=1, address=0x77, sensor_model="bme680")
    )

    assert payload["adapter"] == "mcp2221a"
    assert payload["address"] == "0x77"
    assert payload["temperature_c"] == 23.46
    assert payload["humidity_percent"] == 52.34
    assert payload["pressure_hpa"] == 1007.65
    assert payload["gas_ohms"] == 14001.25
    assert fake_bus.closed is True


def test_read_pmsa003i_maps_pm25_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePM25:
        def __init__(self, i2c, reset_pin) -> None:
            self.i2c = i2c
            self.reset_pin = reset_pin

        def read(self) -> dict[str, int]:
            return {
                "pm10 standard": 4,
                "pm25 standard": 9,
                "pm100 standard": 14,
                "pm10 env": 5,
                "pm25 env": 10,
                "pm100 env": 15,
                "particles 03um": 1200,
                "particles 05um": 800,
                "particles 10um": 400,
                "particles 25um": 180,
                "particles 50um": 75,
                "particles 100um": 20,
            }

    fake_package = ModuleType("adafruit_pm25")
    fake_i2c_module = ModuleType("adafruit_pm25.i2c")
    fake_i2c_module.PM25_I2C = FakePM25
    monkeypatch.setitem(sys.modules, "adafruit_pm25", fake_package)
    monkeypatch.setitem(sys.modules, "adafruit_pm25.i2c", fake_i2c_module)
    monkeypatch.setattr(sensors, "_board_i2c", lambda config: "fake-i2c")

    payload = sensors.read_pmsa003i(
        sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x12, sensor_model="pmsa003i")
    )

    assert payload["pm1_0_standard_ugm3"] == 4
    assert payload["pm2_5_standard_ugm3"] == 9
    assert payload["pm10_standard_ugm3"] == 14
    assert payload["pm1_0_env_ugm3"] == 5
    assert payload["pm2_5_env_ugm3"] == 10
    assert payload["pm10_env_ugm3"] == 15
    assert payload["particles_0_3um_per_0_1l"] == 1200
    assert payload["particles_10um_per_0_1l"] == 20
