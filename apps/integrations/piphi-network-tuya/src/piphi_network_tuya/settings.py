from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-tuya"
INTEGRATION_NAME = "PiPhi Network Tuya"
INTEGRATION_VERSION = "0.1.4"
PROJECT_KIND = "runtime-integration"
PROJECT_PRESET = "local-device-runtime"
PROJECT_DOMAIN = "lan"
DEFAULT_RUNTIME_PORT = 4191
DEFAULT_TUYA_IO_TIMEOUT_SECONDS = 8.0
DEFAULT_TUYA_DISCOVERY_TIMEOUT_SECONDS = 20.0
DEFAULT_POLL_JITTER_SECONDS = 2.0
DEFAULT_POLL_FAILURE_BACKOFF_SECONDS = 15.0
DEFAULT_POLL_ERROR_EVENT_COOLDOWN_SECONDS = 300.0


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def runtime_port() -> int:
    raw_value = (
        os.getenv("PIPHI_RUNTIME_PORT")
        or os.getenv("PORT")
        or str(DEFAULT_RUNTIME_PORT)
    )
    try:
        return int(raw_value)
    except ValueError:
        return DEFAULT_RUNTIME_PORT


def tuya_io_timeout_seconds() -> float:
    return max(
        1.0,
        _env_float("PIPHI_TUYA_IO_TIMEOUT_SECONDS", DEFAULT_TUYA_IO_TIMEOUT_SECONDS),
    )


def tuya_discovery_timeout_seconds() -> float:
    return max(
        1.0,
        _env_float(
            "PIPHI_TUYA_DISCOVERY_TIMEOUT_SECONDS",
            DEFAULT_TUYA_DISCOVERY_TIMEOUT_SECONDS,
        ),
    )


def strict_config_validation() -> bool:
    return _env_bool("PIPHI_TUYA_STRICT_CONFIG_VALIDATION", True)


def poll_jitter_seconds() -> float:
    return max(
        0.0, _env_float("PIPHI_TUYA_POLL_JITTER_SECONDS", DEFAULT_POLL_JITTER_SECONDS)
    )


def poll_failure_backoff_seconds() -> float:
    return max(
        0.0,
        _env_float(
            "PIPHI_TUYA_POLL_FAILURE_BACKOFF_SECONDS",
            DEFAULT_POLL_FAILURE_BACKOFF_SECONDS,
        ),
    )


def poll_error_event_cooldown_seconds() -> float:
    return max(
        0.0,
        _env_float(
            "PIPHI_TUYA_POLL_ERROR_EVENT_COOLDOWN_SECONDS",
            DEFAULT_POLL_ERROR_EVENT_COOLDOWN_SECONDS,
        ),
    )


def runtime_health_timeout_seconds() -> int:
    return max(1, _env_int("PIPHI_RUNTIME_HEALTH_TIMEOUT_SECONDS", 5))
