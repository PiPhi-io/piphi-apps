from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_ADAPTERS = {"linux_spi", "ft232h", "mock"}
SUPPORTED_MODELS = {"auto", "bme680", "bme280", "bmp280"}
MIN_BAUDRATE = 10_000
MAX_BAUDRATE = 1_000_000
MIN_POLL_INTERVAL_SECONDS = 5
MAX_POLL_INTERVAL_SECONDS = 3600
OPERATION_TIMEOUT_SECONDS = 10.0
_adapter_locks: dict[tuple[str, int], threading.Lock] = {}
_adapter_locks_guard = threading.Lock()


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
    config = SensorConfig(
        adapter=str(data.get("adapter") or "linux_spi").strip().lower(),
        bus=int(data.get("bus", 0)),
        chip_select=int(data.get("chip_select", 0)),
        sensor_model=str(data.get("sensor_model") or "auto").strip().lower(),
        baudrate=int(data.get("baudrate") or 100000),
        poll_interval_seconds=int(data.get("poll_interval_seconds") or 30),
    )
    validate_config(config)
    return config


def validate_config(config: SensorConfig) -> None:
    if config.adapter not in SUPPORTED_ADAPTERS:
        raise ValueError(f"Unsupported SPI adapter: {config.adapter}")
    if config.sensor_model not in SUPPORTED_MODELS:
        raise ValueError(f"Unsupported SPI sensor_model: {config.sensor_model}")
    if config.bus != 0:
        raise ValueError(
            f"adapter={config.adapter} uses Blinka's single default SPI bus; bus must be 0"
        )
    if config.chip_select not in {0, 1}:
        raise ValueError("chip_select must be 0 or 1")
    if not MIN_BAUDRATE <= config.baudrate <= MAX_BAUDRATE:
        raise ValueError(f"baudrate must be between {MIN_BAUDRATE} and {MAX_BAUDRATE}")
    if not MIN_POLL_INTERVAL_SECONDS <= config.poll_interval_seconds <= MAX_POLL_INTERVAL_SECONDS:
        raise ValueError(
            f"poll_interval_seconds must be between {MIN_POLL_INTERVAL_SECONDS} and "
            f"{MAX_POLL_INTERVAL_SECONDS}"
        )
    if config.adapter != "mock" and config.sensor_model == "auto":
        raise ValueError("Physical SPI targets require an explicit sensor_model for safe probing")


def adapter_key(config: SensorConfig) -> tuple[str, int]:
    return (config.adapter, config.bus)


def target_key(config: SensorConfig) -> tuple[str, int, int]:
    return (*adapter_key(config), config.chip_select)


def run_serialized(config: SensorConfig, operation: Any) -> Any:
    key = adapter_key(config)
    with _adapter_locks_guard:
        lock = _adapter_locks.setdefault(key, threading.Lock())
    with lock:
        return operation(config)


def discover_devices(config: SensorConfig) -> list[dict[str, Any]]:
    if config.adapter == "mock":
        require_mock_enabled()
        model = "bme280" if config.sensor_model == "auto" else config.sensor_model
    else:
        model = probe_sensor(config)
    return [
        {
            "id": f"spi-{model}-{config.bus}-{config.chip_select}",
            "name": f"SPI {model.upper()} bus {config.bus} CS{config.chip_select}",
            "device_id": f"spi-{config.bus}-{config.chip_select}",
            "adapter": config.adapter,
            "bus": config.bus,
            "chip_select": config.chip_select,
            "model": model,
            "baudrate": config.baudrate,
        }
    ]


def read_state(config: SensorConfig) -> dict[str, Any]:
    if config.adapter == "mock":
        require_mock_enabled()
        return mock_state(config)
    if config.sensor_model == "bme680":
        return read_bme680(config)
    return read_bme280(config)


def probe_sensor(config: SensorConfig) -> str:
    """Instantiate the selected typed driver; its constructor validates chip ID."""
    spi = _spi_bus(config)
    chip_select = _chip_select(config)
    sensor: Any = None
    try:
        if config.sensor_model == "bme680":
            import adafruit_bme680

            sensor = adafruit_bme680.Adafruit_BME680_SPI(
                spi, chip_select, baudrate=config.baudrate
            )
            return "bme680"
        import adafruit_bme280.advanced as adafruit_bme280

        sensor = adafruit_bme280.Adafruit_BME280_SPI(
            spi, chip_select, baudrate=config.baudrate
        )
        return config.sensor_model
    finally:
        _deinit(sensor)
        _deinit(chip_select)
        _deinit(spi)


def mock_state(config: SensorConfig) -> dict[str, Any]:
    seed = int(time.time() // max(config.poll_interval_seconds, 1))
    rng = random.Random(seed)
    return {
        "connected": True,
        "adapter": config.adapter,
        "bus": config.bus,
        "chip_select": config.chip_select,
        "sensor_model": config.sensor_model,
        "baudrate": config.baudrate,
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
    }


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return False
    return True


def _deinit(value: Any) -> None:
    deinit = getattr(value, "deinit", None)
    if callable(deinit):
        deinit()


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

    spi = _spi_bus(config)
    chip_select = _chip_select(config)
    sensor: Any = None
    try:
        sensor = adafruit_bme280.Adafruit_BME280_SPI(
            spi, chip_select, baudrate=config.baudrate
        )
        return {
            "connected": True,
            "adapter": config.adapter,
            "bus": config.bus,
            "chip_select": config.chip_select,
            "sensor_model": config.sensor_model,
            "baudrate": config.baudrate,
            "temperature_c": round(float(sensor.temperature), 2),
            "humidity_percent": round(float(sensor.relative_humidity), 2),
            "pressure_hpa": round(float(sensor.pressure), 2),
            "updated_at": int(time.time()),
        }
    finally:
        _deinit(sensor)
        _deinit(chip_select)
        _deinit(spi)


def read_bme680(config: SensorConfig) -> dict[str, Any]:
    import adafruit_bme680

    spi = _spi_bus(config)
    chip_select = _chip_select(config)
    sensor: Any = None
    try:
        sensor = adafruit_bme680.Adafruit_BME680_SPI(
            spi, chip_select, baudrate=config.baudrate
        )
        return {
            "connected": True,
            "adapter": config.adapter,
            "bus": config.bus,
            "chip_select": config.chip_select,
            "sensor_model": config.sensor_model,
            "baudrate": config.baudrate,
            "temperature_c": round(float(sensor.temperature), 2),
            "humidity_percent": round(float(sensor.humidity), 2),
            "pressure_hpa": round(float(sensor.pressure), 2),
            "gas_ohms": round(float(sensor.gas), 2),
            "updated_at": int(time.time()),
        }
    finally:
        _deinit(sensor)
        _deinit(chip_select)
        _deinit(spi)
