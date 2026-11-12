from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ADDRESSES: dict[str, tuple[int, ...]] = {
    "bme680": (0x76, 0x77),
    "bme280": (0x76, 0x77),
    "bmp280": (0x76, 0x77),
    "aht20": (0x38,),
}
BLINKA_I2C_ADAPTERS = {"mcp2221a", "ft232h"}


@dataclass(frozen=True)
class SensorConfig:
    adapter: str = "linux_i2c"
    bus: int = 1
    address: int | None = None
    sensor_model: str = "auto"
    poll_interval_seconds: int = 30


def parse_address(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    base = 16 if text.startswith("0x") else 10
    return int(text, base)


def normalize_config(payload: dict[str, Any] | None) -> SensorConfig:
    data = payload or {}
    return SensorConfig(
        adapter=str(data.get("adapter") or "linux_i2c").strip().lower(),
        bus=int(data.get("bus") or 1),
        address=parse_address(data.get("address")),
        sensor_model=str(data.get("sensor_model") or "auto").strip().lower(),
        poll_interval_seconds=max(5, int(data.get("poll_interval_seconds") or 30)),
    )


def scan_i2c_addresses(config: SensorConfig) -> list[int]:
    if config.adapter == "mock":
        require_mock_enabled()
        return [0x76, 0x38]
    if config.adapter in BLINKA_I2C_ADAPTERS:
        return scan_blinka_i2c_addresses(config)
    try:
        from smbus2 import SMBus
    except ImportError:
        return []

    found: list[int] = []
    with SMBus(config.bus) as bus:
        for address in range(0x03, 0x78):
            try:
                bus.write_quick(address)
            except OSError:
                continue
            found.append(address)
    return found


def scan_blinka_i2c_addresses(config: SensorConfig) -> list[int]:
    try:
        i2c = _board_i2c(config)
    except ImportError:
        return []
    if not hasattr(i2c, "try_lock") or not hasattr(i2c, "scan"):
        return []
    locked = False
    try:
        locked = bool(i2c.try_lock())
        if not locked:
            return []
        return [int(address) for address in i2c.scan()]
    finally:
        if locked and hasattr(i2c, "unlock"):
            i2c.unlock()


def discover_devices(config: SensorConfig) -> list[dict[str, Any]]:
    addresses = [config.address] if config.address is not None else scan_i2c_addresses(config)
    devices: list[dict[str, Any]] = []
    for address in addresses:
        if address is None:
            continue
        model = config.sensor_model if config.sensor_model != "auto" else guess_model(address)
        devices.append(
            {
                "id": f"i2c-{model}-{address:02x}",
                "name": f"I2C {model.upper()} 0x{address:02X}",
                "device_id": f"i2c-{config.bus}-{address:02x}",
                "address": f"0x{address:02X}",
                "adapter": config.adapter,
                "bus": config.bus,
                "model": model,
            }
        )
    return devices


def guess_model(address: int) -> str:
    if address == 0x38:
        return "aht20"
    if address in (0x76, 0x77):
        return "bme280"
    return "generic"


def read_state(config: SensorConfig) -> dict[str, Any]:
    if config.adapter == "mock":
        require_mock_enabled()
        return mock_state(config)
    if config.sensor_model in {"aht20", "ahtx0"}:
        return read_aht20(config)
    if config.sensor_model == "bme680":
        return read_bme680(config)
    if config.sensor_model in {"bme280", "bmp280", "auto"}:
        return read_bme280(config)
    return {"connected": True, "addresses": [f"0x{address:02X}" for address in scan_i2c_addresses(config)]}


def mock_state(config: SensorConfig) -> dict[str, Any]:
    seed = int(time.time() // max(config.poll_interval_seconds, 1))
    rng = random.Random(seed)
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "address": f"0x{(config.address or 0x76):02X}",
        "sensor_model": config.sensor_model,
        "temperature_c": round(21.5 + rng.random() * 3, 2),
        "humidity_percent": round(42 + rng.random() * 12, 2),
        "pressure_hpa": round(1008 + rng.random() * 12, 2),
        "gas_ohms": round(12000 + rng.random() * 5000, 2),
        "updated_at": int(time.time()),
    }


def mock_hardware_allowed() -> bool:
    return str(os.getenv("PIPHI_ALLOW_MOCK_HARDWARE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_mock_enabled() -> None:
    if not mock_hardware_allowed():
        raise RuntimeError(
            "Mock hardware is disabled. Set PIPHI_ALLOW_MOCK_HARDWARE=true to use adapter=mock."
        )


def hardware_diagnostics() -> dict[str, Any]:
    i2c_nodes = sorted(str(path) for path in Path("/dev").glob("i2c-*"))
    return {
        "default_adapter": "linux_i2c",
        "mock_enabled": mock_hardware_allowed(),
        "linux_i2c": {
            "device_nodes": i2c_nodes,
            "available": bool(i2c_nodes),
            "smbus2": _module_available("smbus2"),
            "pimoroni_bme280": _module_available("bme280"),
            "pimoroni_bme680": _module_available("bme680"),
        },
        "mcp2221a": {
            "blinka_env_enabled": _blinka_env_enabled("BLINKA_MCP2221"),
            "board": _module_available("board"),
            "busio": _module_available("busio"),
            "ahtx0": _module_available("adafruit_ahtx0"),
            "adafruit_bme280": _module_available("adafruit_bme280"),
            "adafruit_bme680": _module_available("adafruit_bme680"),
        },
        "ft232h": {
            "blinka_env_enabled": _blinka_env_enabled("BLINKA_FT232H"),
            "board": _module_available("board"),
            "busio": _module_available("busio"),
            "ahtx0": _module_available("adafruit_ahtx0"),
            "adafruit_bme280": _module_available("adafruit_bme280"),
            "adafruit_bme680": _module_available("adafruit_bme680"),
        },
    }


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return False
    return True


def _blinka_env_enabled(env_name: str) -> bool:
    return str(os.getenv(env_name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _board_i2c(config: SensorConfig) -> Any:
    if config.adapter in BLINKA_I2C_ADAPTERS:
        import board

        return board.I2C()
    import board
    import busio

    return busio.I2C(board.SCL, board.SDA)


def read_aht20(config: SensorConfig) -> dict[str, Any]:
    import adafruit_ahtx0

    sensor = adafruit_ahtx0.AHTx0(_board_i2c(config))
    return {
        "connected": True,
        "temperature_c": round(float(sensor.temperature), 2),
        "humidity_percent": round(float(sensor.relative_humidity), 2),
        "updated_at": int(time.time()),
    }


def read_bme280(config: SensorConfig) -> dict[str, Any]:
    if config.adapter == "linux_i2c":
        try:
            return read_bme280_pimoroni(config)
        except ImportError:
            return read_bme280_adafruit(config)
    return read_bme280_adafruit(config)


def read_bme280_pimoroni(config: SensorConfig) -> dict[str, Any]:
    from bme280 import BME280
    from smbus2 import SMBus

    bus = SMBus(config.bus)
    try:
        sensor = BME280(i2c_dev=bus, i2c_addr=config.address or 0x76)
    except TypeError:
        sensor = BME280(i2c_dev=bus)
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "address": f"0x{(config.address or 0x76):02X}",
        "sensor_model": config.sensor_model,
        "temperature_c": round(float(sensor.get_temperature()), 2),
        "humidity_percent": round(float(sensor.get_humidity()), 2),
        "pressure_hpa": round(float(sensor.get_pressure()), 2),
        "updated_at": int(time.time()),
    }


def read_bme280_adafruit(config: SensorConfig) -> dict[str, Any]:
    import adafruit_bme280.advanced as adafruit_bme280

    sensor = adafruit_bme280.Adafruit_BME280_I2C(_board_i2c(config), address=config.address or 0x76)
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "address": f"0x{(config.address or 0x76):02X}",
        "sensor_model": config.sensor_model,
        "temperature_c": round(float(sensor.temperature), 2),
        "humidity_percent": round(float(sensor.relative_humidity), 2),
        "pressure_hpa": round(float(sensor.pressure), 2),
        "updated_at": int(time.time()),
    }


def read_bme680(config: SensorConfig) -> dict[str, Any]:
    if config.adapter == "linux_i2c":
        try:
            return read_bme680_pimoroni(config)
        except ImportError:
            return read_bme680_adafruit(config)
    return read_bme680_adafruit(config)


def read_bme680_pimoroni(config: SensorConfig) -> dict[str, Any]:
    import bme680

    sensor = bme680.BME680(config.address or bme680.I2C_ADDR_PRIMARY)
    sensor.get_sensor_data()
    output = sensor.data
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "address": f"0x{(config.address or bme680.I2C_ADDR_PRIMARY):02X}",
        "sensor_model": config.sensor_model,
        "temperature_c": round(float(output.temperature), 2),
        "humidity_percent": round(float(output.humidity), 2),
        "pressure_hpa": round(float(output.pressure), 2),
        "gas_ohms": round(float(output.gas_resistance), 2),
        "updated_at": int(time.time()),
    }


def read_bme680_adafruit(config: SensorConfig) -> dict[str, Any]:
    import adafruit_bme680

    sensor = adafruit_bme680.Adafruit_BME680_I2C(_board_i2c(config), address=config.address or 0x77)
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "address": f"0x{(config.address or 0x77):02X}",
        "sensor_model": config.sensor_model,
        "temperature_c": round(float(sensor.temperature), 2),
        "humidity_percent": round(float(sensor.humidity), 2),
        "pressure_hpa": round(float(sensor.pressure), 2),
        "gas_ohms": round(float(sensor.gas), 2),
        "updated_at": int(time.time()),
    }
