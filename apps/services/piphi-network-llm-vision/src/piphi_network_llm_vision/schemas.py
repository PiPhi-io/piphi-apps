from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str
    alias: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    poll_interval_seconds: int | None = None
    service_name: str | None = None
