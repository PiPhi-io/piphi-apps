from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SensorConfig:
    adapter: str = "linux_spi"
    bus: int = 0
    chip_select: int = 0
    sensor_model: str = "auto"
    baudrate: int = 100000
    poll_interval_seconds: int = 30


def normalize_config(payload: dict[str, Any] | None) -> SensorConfig:
    data = payload or {}
    return SensorConfig(
        adapter=str(data.get("adapter") or "linux_spi").strip().lower(),
        bus=int(data.get("bus") or 0),
        chip_select=int(data.get("chip_select") or 0),
        sensor_model=str(data.get("sensor_model") or "auto").strip().lower(),
        baudrate=int(data.get("baudrate") or 100000),
        poll_interval_seconds=max(5, int(data.get("poll_interval_seconds") or 30)),
    )


def discover_devices(config: SensorConfig) -> list[dict[str, Any]]:
    if config.adapter == "mock":
        require_mock_enabled()
    model = "bme280" if config.sensor_model == "auto" else config.sensor_model
    return [
        {
            "id": f"spi-{model}-{config.bus}-{config.chip_select}",
            "name": f"SPI {model.upper()} bus {config.bus} CS{config.chip_select}",
            "device_id": f"spi-{config.bus}-{config.chip_select}",
            "adapter": config.adapter,
            "bus": config.bus,
            "chip_select": config.chip_select,
            "model": model,
        }
    ]


def read_state(config: SensorConfig) -> dict[str, Any]:
    if config.adapter == "mock":
        require_mock_enabled()
        return mock_state(config)
    if config.sensor_model == "bme680":
        return read_bme680(config)
    return read_bme280(config)


def mock_state(config: SensorConfig) -> dict[str, Any]:
    seed = int(time.time() // max(config.poll_interval_seconds, 1))
    rng = random.Random(seed)
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "chip_select": config.chip_select,
        "sensor_model": config.sensor_model,
        "temperature_c": round(21 + rng.random() * 4, 2),
        "humidity_percent": round(40 + rng.random() * 15, 2),
        "pressure_hpa": round(1006 + rng.random() * 14, 2),
        "gas_ohms": round(11000 + rng.random() * 6000, 2),
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
    spi_nodes = sorted(str(path) for path in Path("/dev").glob("spidev*"))
    return {
        "default_adapter": "linux_spi",
        "mock_enabled": mock_hardware_allowed(),
        "linux_spi": {
            "device_nodes": spi_nodes,
            "available": bool(spi_nodes),
            "spidev": _module_available("spidev"),
            "board": _module_available("board"),
            "busio": _module_available("busio"),
            "digitalio": _module_available("digitalio"),
        },
        "ft232h": {
            "board": _module_available("board"),
            "busio": _module_available("busio"),
            "digitalio": _module_available("digitalio"),
            "adafruit_bme280": _module_available("adafruit_bme280"),
            "adafruit_bme680": _module_available("adafruit_bme680"),
        },
        "shared_libraries": {
            "pimoroni_bme280": _module_available("bme280"),
            "pimoroni_bme680": _module_available("bme680"),
        },
    }


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return False
    return True


def _spi_bus(config: SensorConfig) -> Any:
    if config.adapter == "ft232h":
        import board
        import busio

        return busio.SPI(board.SCK, board.MOSI, board.MISO)
    import board
    import busio

    return busio.SPI(board.SCK, board.MOSI, board.MISO)


def _chip_select(config: SensorConfig) -> Any:
    import board
    import digitalio

    if config.adapter == "ft232h":
        candidate_names = ("C0", "D5") if config.chip_select == 0 else ("C1", "D6")
    else:
        candidate_names = ("CE0", "D5") if config.chip_select == 0 else ("CE1", "D6")
    for pin_name in candidate_names:
        if hasattr(board, pin_name):
            return digitalio.DigitalInOut(getattr(board, pin_name))
    raise RuntimeError(f"No board pin found for SPI chip select {config.chip_select}")


def read_bme280(config: SensorConfig) -> dict[str, Any]:
    import adafruit_bme280.advanced as adafruit_bme280

    sensor = adafruit_bme280.Adafruit_BME280_SPI(_spi_bus(config), _chip_select(config))
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "chip_select": config.chip_select,
        "sensor_model": config.sensor_model,
        "temperature_c": round(float(sensor.temperature), 2),
        "humidity_percent": round(float(sensor.relative_humidity), 2),
        "pressure_hpa": round(float(sensor.pressure), 2),
        "updated_at": int(time.time()),
    }


def read_bme680(config: SensorConfig) -> dict[str, Any]:
    import adafruit_bme680

    sensor = adafruit_bme680.Adafruit_BME680_SPI(_spi_bus(config), _chip_select(config))
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "chip_select": config.chip_select,
        "sensor_model": config.sensor_model,
        "temperature_c": round(float(sensor.temperature), 2),
        "humidity_percent": round(float(sensor.humidity), 2),
        "pressure_hpa": round(float(sensor.pressure), 2),
        "gas_ohms": round(float(sensor.gas), 2),
        "updated_at": int(time.time()),
    }
