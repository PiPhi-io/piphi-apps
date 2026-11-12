from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    station_id: str | None = None
    host: str | None = None
    alias: str | None = None
    api_token: str | None = None
    username: str | None = None
    password: str | None = None
    base_url: str | None = None
    poll_interval_seconds: int | None = None
    service_name: str | None = None
