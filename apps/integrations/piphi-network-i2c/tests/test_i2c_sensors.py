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


def test_hardware_diagnostics_advertises_mock_only() -> None:
    diagnostics = sensors.hardware_diagnostics()

    assert diagnostics == {
        "default_adapter": "mock",
        "supported_adapters": ["mock"],
        "mock_enabled": False,
    }


def test_parse_address_supports_hex_and_decimal() -> None:
    assert sensors.parse_address("0x76") == 0x76
    assert sensors.parse_address("56") == 56


def test_discover_devices_uses_verified_chip_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sensors, "read_bosch_chip_id", lambda config, address: 0x61)
    devices = sensors.discover_devices(
        sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x76, sensor_model="auto")
    )

    assert devices[0]["model"] == "bme680"
    assert devices[0]["address"] == "0x76"


def test_read_state_routes_explicit_pmsa003i_without_address_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sensors,
        "read_pmsa003i",
        lambda config: {"connected": True, "sensor_model": "pmsa003i", "pm2_5_standard_ugm3": 11},
    )

    payload = sensors.read_state(
        sensors.SensorConfig(adapter="mcp2221a", bus=1, address=0x12, sensor_model="pmsa003i")
    )

    assert payload["sensor_model"] == "pmsa003i"
    assert payload["pm2_5_standard_ugm3"] == 11


def test_discovery_drops_wrong_explicit_bosch_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sensors, "read_bosch_chip_id", lambda config, address: 0x61)

    devices = sensors.discover_devices(
        sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x76, sensor_model="bme280")
    )

    assert devices == []


def test_generic_normal_read_never_scans_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sensors,
        "scan_i2c_addresses",
        lambda config: (_ for _ in ()).throw(AssertionError("normal read must not scan")),
    )

    with pytest.raises(RuntimeError, match="Generic I2C reads are unsupported"):
        sensors.read_state(
            sensors.SensorConfig(
                adapter="linux_i2c",
                bus=1,
                address=0x40,
                sensor_model="generic",
                allow_scan=False,
            )
        )


def test_auto_normal_read_without_target_never_scans_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sensors,
        "scan_i2c_addresses",
        lambda config: (_ for _ in ()).throw(AssertionError("normal read must not scan")),
    )

    with pytest.raises(RuntimeError, match="Generic I2C reads are unsupported"):
        sensors.read_state(
            sensors.SensorConfig(
                adapter="linux_i2c",
                bus=1,
                sensor_model="auto",
                allow_scan=False,
            )
        )


def test_generic_explicit_target_discovery_requires_maintenance_scan() -> None:
    with pytest.raises(RuntimeError, match="cannot safely verify"):
        sensors.discover_devices(
            sensors.SensorConfig(
                adapter="linux_i2c",
                bus=1,
                address=0x40,
                sensor_model="generic",
                allow_scan=False,
            )
        )


def test_generic_full_bus_scan_requires_explicit_maintenance_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scans: list[tuple[str, int]] = []
    monkeypatch.setattr(
        sensors,
        "scan_i2c_addresses",
        lambda config: scans.append((config.adapter, config.bus)) or [0x40],
    )

    devices = sensors.discover_devices(
        sensors.SensorConfig(
            adapter="linux_i2c",
            bus=3,
            sensor_model="generic",
            allow_scan=True,
        )
    )

    assert scans == [("linux_i2c", 3)]
    assert devices[0]["id"] == "i2c-linux_i2c-3-40"


def test_i2c_discovery_ids_include_adapter_bus_and_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sensors, "read_bosch_chip_id", lambda config, address: 0x60)

    bus_one = sensors.discover_devices(
        sensors.SensorConfig(adapter="linux_i2c", bus=1, address=0x76, sensor_model="auto")
    )[0]
    bus_two = sensors.discover_devices(
        sensors.SensorConfig(adapter="linux_i2c", bus=2, address=0x76, sensor_model="auto")
    )[0]

    assert bus_one["id"] == "i2c-linux_i2c-1-76"
    assert bus_two["id"] == "i2c-linux_i2c-2-76"
    assert bus_one["id"] != bus_two["id"]


def test_normalize_config_rejects_ranges_and_ignored_bus_combinations() -> None:
    with pytest.raises(ValueError, match="0x03..0x77"):
        sensors.normalize_config({"address": "0x78", "sensor_model": "generic"})
    with pytest.raises(ValueError, match="Unsupported I2C adapter"):
        sensors.normalize_config({"adapter": "ft232h", "bus": 2, "sensor_model": "generic"})


def test_linux_config_is_not_publicly_supported() -> None:
    with pytest.raises(ValueError, match="Unsupported I2C adapter: linux_i2c"):
        sensors.normalize_config(
            {"adapter": "linux_i2c", "bus": 1, "address": "0x76", "sensor_model": "bme280"}
        )


def test_preflight_rejects_permission_and_kernel_driver_without_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = tmp_path / "dev"
    sys_root = tmp_path / "sys"
    dev.mkdir()
    node = dev / "i2c-1"
    node.touch()
    config = sensors.SensorConfig(
        adapter="linux_i2c", bus=1, address=0x76, sensor_model="bme280", adapter_id="adapter01"
    )
    monkeypatch.setattr(sensors.os, "access", lambda *_args: False)
    with pytest.raises(PermissionError, match="not readable/writable"):
        sensors.preflight_target(config, dev_root=dev, sys_root=sys_root)
    monkeypatch.setattr(sensors.os, "access", lambda *_args: True)
    driver = sys_root / "bus" / "i2c" / "devices" / "1-0076" / "driver"
    driver.mkdir(parents=True)
    with pytest.raises(BlockingIOError, match="automatic unbind is forbidden"):
        sensors.preflight_target(config, dev_root=dev, sys_root=sys_root)


def test_adapter_identity_is_stable_opaque_and_excludes_raw_id() -> None:
    config = sensors.SensorConfig(adapter="linux_i2c", adapter_id="private-adapter-01", address=0x76)
    fingerprint = sensors.adapter_fingerprint(config)
    assert fingerprint == sensors.adapter_fingerprint(config)
    assert "private" not in fingerprint


def test_auto_detected_model_is_reported_effectively(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sensors, "read_bosch_chip_id", lambda config, address: 0x61)
    monkeypatch.setattr(
        sensors,
        "read_bme680",
        lambda config: {"connected": True, "sensor_model": config.sensor_model},
    )

    payload = sensors.read_state(
        sensors.SensorConfig(adapter="linux_i2c", address=0x76, sensor_model="auto")
    )

    assert payload["sensor_model"] == "bme680"


def test_linux_bme280_handle_closes_when_read_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBus:
        closed = False

        def close(self) -> None:
            self.closed = True

    class BrokenSensor:
        def __init__(self, **kwargs) -> None:
            pass

        def get_temperature(self) -> float:
            raise OSError("read failed")

    fake_bus = FakeBus()
    monkeypatch.setitem(sys.modules, "smbus2", SimpleNamespace(SMBus=lambda bus: fake_bus))
    monkeypatch.setitem(sys.modules, "bme280", SimpleNamespace(BME280=BrokenSensor))

    with pytest.raises(OSError, match="read failed"):
        sensors.read_bme280_pimoroni(
            sensors.SensorConfig(adapter="linux_i2c", address=0x76, sensor_model="bme280")
        )

    assert fake_bus.closed is True


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
