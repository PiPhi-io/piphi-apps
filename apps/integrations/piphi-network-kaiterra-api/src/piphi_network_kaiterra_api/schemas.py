from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str | None = None
    alias: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    device_udid: str | None = None
    poll_interval_seconds: int | None = None
