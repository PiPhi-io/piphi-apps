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
    "pmsa003i": (0x12,),
}
BLINKA_I2C_ADAPTERS = {"ft232h"}
BOARD_I2C_ADAPTERS = {"mcp2221a", "ft232h"}
DEFAULT_MCP2221_I2C_CLOCK = 100_000


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
    if config.adapter == "mcp2221a":
        return scan_mcp2221_i2c_addresses(config)
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


def scan_mcp2221_i2c_addresses(config: SensorConfig) -> list[int]:
    try:
        easy_mcp2221 = _import_easy_mcp2221()
        bus = _mcp2221_smbus(config)
    except ImportError:
        return []
    except Exception as exc:
        raise RuntimeError(f"Unable to open MCP2221A device: {exc}") from exc

    not_ack_error = getattr(
        getattr(easy_mcp2221, "exceptions", None),
        "NotAckError",
        OSError,
    )
    mcp = getattr(bus, "mcp", None)
    if mcp is None or not hasattr(mcp, "I2C_read"):
        _close_i2c_handle(bus)
        return []

    found: list[int] = []
    try:
        for address in range(0x03, 0x78):
            try:
                mcp.I2C_read(address)
            except not_ack_error:
                continue
            except OSError:
                continue
            found.append(address)
        return found
    except Exception as exc:
        raise RuntimeError(f"MCP2221A scan failed: {exc}") from exc
    finally:
        _close_i2c_handle(bus)


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
        model = resolve_sensor_model(config, addresses=[address])
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


def resolve_sensor_model(config: SensorConfig, *, addresses: list[int] | None = None) -> str:
    if config.sensor_model != "auto":
        return config.sensor_model
    candidate_addresses = addresses if addresses is not None else (
        [config.address] if config.address is not None else scan_i2c_addresses(config)
    )
    for address in candidate_addresses:
        guessed = guess_model(address)
        if guessed != "generic":
            return guessed
    return "generic"


def guess_model(address: int) -> str:
    if address == 0x12:
        return "pmsa003i"
    if address == 0x38:
        return "aht20"
    if address in (0x76, 0x77):
        return "bme280"
    return "generic"


def read_state(config: SensorConfig) -> dict[str, Any]:
    resolved_model = resolve_sensor_model(config)
    if config.adapter == "mock":
        require_mock_enabled()
        return mock_state(config)
    if resolved_model in {"pmsa003i", "pm25"}:
        return read_pmsa003i(config)
    if resolved_model in {"aht20", "ahtx0"}:
        return read_aht20(config)
    if resolved_model == "bme680":
        return read_bme680(config)
    if resolved_model in {"bme280", "bmp280"}:
        return read_bme280(config)
    return {"connected": True, "addresses": [f"0x{address:02X}" for address in scan_i2c_addresses(config)]}


def mock_state(config: SensorConfig) -> dict[str, Any]:
    seed = int(time.time() // max(config.poll_interval_seconds, 1))
    rng = random.Random(seed)
    resolved_model = resolve_sensor_model(
        config,
        addresses=[config.address] if config.address is not None else [0x76],
    )
    if resolved_model in {"pmsa003i", "pm25"}:
        pm25 = round(8 + rng.random() * 12, 2)
        return {
            "connected": True,
            "adapter": config.adapter,
            "bus": config.bus,
            "address": f"0x{(config.address or 0x12):02X}",
            "sensor_model": resolved_model,
            "pm1_0_standard_ugm3": round(pm25 * 0.7, 2),
            "pm2_5_standard_ugm3": pm25,
            "pm10_standard_ugm3": round(pm25 * 1.35, 2),
            "pm1_0_env_ugm3": round(pm25 * 0.75, 2),
            "pm2_5_env_ugm3": round(pm25 * 1.05, 2),
            "pm10_env_ugm3": round(pm25 * 1.45, 2),
            "particles_0_3um_per_0_1l": int(500 + rng.random() * 900),
            "particles_0_5um_per_0_1l": int(250 + rng.random() * 450),
            "particles_1_0um_per_0_1l": int(100 + rng.random() * 180),
            "particles_2_5um_per_0_1l": int(40 + rng.random() * 90),
            "particles_5_0um_per_0_1l": int(10 + rng.random() * 35),
            "particles_10um_per_0_1l": int(2 + rng.random() * 10),
            "updated_at": int(time.time()),
        }
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "address": f"0x{(config.address or 0x76):02X}",
        "sensor_model": resolved_model,
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
            "adafruit_pm25": _module_available("adafruit_pm25"),
        },
        "mcp2221a": {
            "easy_mcp2221": _module_available("EasyMCP2221"),
            "blinka_env_enabled": _blinka_env_enabled("BLINKA_MCP2221"),
            "board": _module_available("board"),
            "busio": _module_available("busio"),
            "pimoroni_bme280": _module_available("bme280"),
            "pimoroni_bme680": _module_available("bme680"),
            "adafruit_pm25": _module_available("adafruit_pm25"),
            "ahtx0": _module_available("adafruit_ahtx0"),
            "adafruit_bme280": _module_available("adafruit_bme280"),
            "adafruit_bme680": _module_available("adafruit_bme680"),
        },
        "ft232h": {
            "blinka_env_enabled": _blinka_env_enabled("BLINKA_FT232H"),
            "board": _module_available("board"),
            "busio": _module_available("busio"),
            "adafruit_pm25": _module_available("adafruit_pm25"),
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


def _import_easy_mcp2221() -> Any:
    import EasyMCP2221

    return EasyMCP2221


def _mcp2221_smbus(config: SensorConfig, *, clock: int = DEFAULT_MCP2221_I2C_CLOCK) -> Any:
    easy_mcp2221 = _import_easy_mcp2221()
    bus_index = max(int(config.bus or 1), 1)
    return easy_mcp2221.SMBus(bus=bus_index, clock=clock)


def _close_i2c_handle(handle: Any) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        close()


def _board_i2c(config: SensorConfig) -> Any:
    if config.adapter in BOARD_I2C_ADAPTERS:
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


def read_pmsa003i(config: SensorConfig) -> dict[str, Any]:
    from adafruit_pm25.i2c import PM25_I2C

    sensor = PM25_I2C(_board_i2c(config), None)
    payload = sensor.read()
    address = config.address or 0x12
    resolved_model = resolve_sensor_model(config, addresses=[address])
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "address": f"0x{address:02X}",
        "sensor_model": resolved_model,
        "pm1_0_standard_ugm3": int(payload["pm10 standard"]),
        "pm2_5_standard_ugm3": int(payload["pm25 standard"]),
        "pm10_standard_ugm3": int(payload["pm100 standard"]),
        "pm1_0_env_ugm3": int(payload["pm10 env"]),
        "pm2_5_env_ugm3": int(payload["pm25 env"]),
        "pm10_env_ugm3": int(payload["pm100 env"]),
        "particles_0_3um_per_0_1l": int(payload["particles 03um"]),
        "particles_0_5um_per_0_1l": int(payload["particles 05um"]),
        "particles_1_0um_per_0_1l": int(payload["particles 10um"]),
        "particles_2_5um_per_0_1l": int(payload["particles 25um"]),
        "particles_5_0um_per_0_1l": int(payload["particles 50um"]),
        "particles_10um_per_0_1l": int(payload["particles 100um"]),
        "updated_at": int(time.time()),
    }


def read_bme280(config: SensorConfig) -> dict[str, Any]:
    if config.adapter == "mcp2221a":
        try:
            return read_bme280_mcp2221(config)
        except ImportError as exc:
            try:
                return read_bme280_adafruit(config)
            except ImportError as fallback_exc:
                raise ImportError(
                    f"{exc}. MCP2221A Blinka fallback also unavailable: {fallback_exc}"
                ) from fallback_exc
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


def read_bme280_mcp2221(config: SensorConfig) -> dict[str, Any]:
    bus = _mcp2221_smbus(config)
    try:
        from bme280 import BME280

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
    finally:
        _close_i2c_handle(bus)


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
    if config.adapter == "mcp2221a":
        try:
            return read_bme680_mcp2221(config)
        except ImportError as exc:
            try:
                return read_bme680_adafruit(config)
            except ImportError as fallback_exc:
                raise ImportError(
                    f"{exc}. MCP2221A Blinka fallback also unavailable: {fallback_exc}"
                ) from fallback_exc
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


def read_bme680_mcp2221(config: SensorConfig) -> dict[str, Any]:
    bus = _mcp2221_smbus(config)
    try:
        import bme680

        sensor = bme680.BME680(
            i2c_addr=config.address or bme680.I2C_ADDR_PRIMARY,
            i2c_device=bus,
        )
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
    finally:
        _close_i2c_handle(bus)


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
